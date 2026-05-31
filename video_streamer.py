"""
VideoStreamer — FPV Video Module
=================================
Captura video desde la capturadora USB (RCA), lo transmite via WebRTC
y graba MP4 sincronizado con las sesiones de telemetría.

Dependencias:
    pip install aiortc opencv-python

Uso independiente (test):
    python video_streamer.py --device 0 --width 1280 --height 720
"""

import asyncio
import concurrent.futures
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict
import fractions

import cv2
import numpy as np
import json

from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer
from av import VideoFrame

log = logging.getLogger("video_streamer")

LOGS_DIR    = Path(__file__).parent / "logs"
VIDEO_DIR   = LOGS_DIR / "video"
CONFIG_FILE = Path(__file__).parent / "video_config.json"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# 0. Config Loader
# ──────────────────────────────────────────────

def load_video_config() -> dict:
    """Carga video_config.json generado por video_calibrate.py"""
    defaults = {
        "brightness":  0,
        "contrast":    32,
        "saturation":  60,
        "gamma":       1.0,
        "hist_eq":     False,
        "ntsc":        True,
        # White Balance por canal (nuevo)
        "wb_r":        1.0,
        "wb_g":        1.0,
        "wb_b":        1.0,
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = {**defaults, **json.load(f)}
            log.info(f"[Video] Config cargada: {cfg}")
            return cfg
        except Exception as e:
            log.warning(f"[Video] Error leyendo config, usando defaults: {e}")
    return defaults

def apply_white_balance(frame: np.ndarray, wb_r: float, wb_g: float, wb_b: float) -> np.ndarray:
    """Corrección de White Balance multiplicando cada canal RGB."""
    if wb_r == 1.0 and wb_g == 1.0 and wb_b == 1.0:
        return frame
    result = frame.astype(np.float32)
    result[:, :, 0] = np.clip(result[:, :, 0] * wb_b, 0, 255)  # B
    result[:, :, 1] = np.clip(result[:, :, 1] * wb_g, 0, 255)  # G
    result[:, :, 2] = np.clip(result[:, :, 2] * wb_r, 0, 255)  # R
    return result.astype(np.uint8)


def apply_gamma(frame: np.ndarray, gamma: float) -> np.ndarray:
    """Corrección de gamma via LUT."""
    if gamma == 1.0:
        return frame
    inv_gamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** inv_gamma) * 255
                      for i in range(256)], dtype="uint8")
    return cv2.LUT(frame, table)


def apply_hist_eq(frame: np.ndarray) -> np.ndarray:
    """Ecualización de histograma en canal Y (luminancia)."""
    yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
    yuv[:, :, 0] = cv2.equalizeHist(yuv[:, :, 0])
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)


def apply_software_correction(frame: np.ndarray, cfg: dict) -> np.ndarray:
    """Aplica todas las correcciones de software al frame."""
    result = frame
    # 1. White Balance (primero, antes del gamma)
    wb_r = cfg.get("wb_r", 1.0)
    wb_g = cfg.get("wb_g", 1.0)
    wb_b = cfg.get("wb_b", 1.0)
    if wb_r != 1.0 or wb_g != 1.0 or wb_b != 1.0:
        result = apply_white_balance(result, wb_r, wb_g, wb_b)
    # 2. Gamma
    if cfg.get("gamma", 1.0) != 1.0:
        result = apply_gamma(result, cfg["gamma"])
    # 3. Ecualización de histograma
    if cfg.get("hist_eq", False):
        result = apply_hist_eq(result)
    return result


# ──────────────────────────────────────────────
# 1. Device Manager
# ──────────────────────────────────────────────

class DeviceManager:
    """Enumera los dispositivos de captura de video disponibles."""

    @staticmethod
    def _test_device(idx: int) -> Optional[dict]:
        """Prueba un índice de dispositivo y retorna su info o None."""
        try:
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                return None
            ret, frame = cap.read()
            if not ret or frame is None:
                cap.release()
                return None
            result = {
                "id":        idx,
                "name":      DeviceManager.get_device_name(idx),
                "width":     int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height":    int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps":       cap.get(cv2.CAP_PROP_FPS) or 30,
                "available": True,
            }
            cap.release()
            return result
        except Exception:
            return None

    @staticmethod
    def enumerate() -> list[dict]:
        """
        Prueba índices 0-4 en paralelo (máx 5 workers) con timeout de 12s total.
        Usa DirectShow en Windows para menor latencia.
        """
        devices = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futs = [executor.submit(DeviceManager._test_device, idx) for idx in range(5)]
            try:
                for fut in concurrent.futures.as_completed(futs, timeout=12):
                    try:
                        result = fut.result()
                        if result:
                            devices.append(result)
                    except Exception:
                        pass
            except concurrent.futures.TimeoutError:
                pass
        return sorted(devices, key=lambda d: d["id"])

    @staticmethod
    def get_device_name(device_id: int) -> str:
        """Intenta obtener el nombre del dispositivo via DirectShow (Windows)."""
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-PnpDevice -Class Camera | Select-Object -ExpandProperty FriendlyName"],
                capture_output=True, text=True, timeout=5
            )
            names = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            if device_id < len(names):
                return names[device_id]
        except Exception:
            pass
        return f"Capture Device {device_id}"


# ──────────────────────────────────────────────
# 2. Video Capture (OpenCV)
# ──────────────────────────────────────────────

class VideoCapture:
    """Gestiona la captura de frames desde la capturadora USB."""

    def __init__(self):
        self._cap:      Optional[cv2.VideoCapture] = None
        self._frame:    Optional[np.ndarray]       = None
        self._lock      = asyncio.Lock()
        self._task:     Optional[asyncio.Task]     = None
        self._cfg:      dict                       = load_video_config()

        self.is_running = False
        self.device_id  = 0
        self.width      = 1280
        self.height     = 720
        self.fps        = 30.0
        self.frame_count = 0

    async def start(self, device_id: int = 0,
                    width: int = 1280, height: int = 720,
                    fps: int = 30) -> bool:
        """Abre la capturadora y comienza el loop de lectura."""
        if self.is_running:
            await self.stop()

        self.device_id = device_id
        self.width     = width
        self.height    = height
        self.fps       = float(fps)

        # Cargar configuración de calibración
        self._cfg = load_video_config()

        # Intentar con DirectShow primero (Windows, menor latencia)
        cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(device_id)

        if not cap.isOpened():
            log.error(f"No se pudo abrir dispositivo {device_id}")
            return False

        # Configurar resolución y FPS
        fps_target = 29.97 if self._cfg.get("ntsc", True) else 25.0
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS,          fps_target)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Aplicar propiedades de calibración al driver
        cap.set(cv2.CAP_PROP_BRIGHTNESS,  self._cfg.get("brightness", 0))
        cap.set(cv2.CAP_PROP_CONTRAST,    self._cfg.get("contrast", 32))
        cap.set(cv2.CAP_PROP_SATURATION,  self._cfg.get("saturation", 60))

        # Verificar frame
        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            log.error(f"Dispositivo {device_id} no devuelve frames")
            return False

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        log.info(f"Capturadora: device={device_id} {actual_w}x{actual_h} @ {actual_fps:.1f}fps | cfg={self._cfg}")

        self._cap        = cap
        self._frame      = frame
        self.is_running  = True
        self.frame_count = 0

        # Loop de lectura en thread separado (sin bloquear el event loop)
        self._task = asyncio.create_task(self._read_loop())
        return True

    async def stop(self):
        """Detiene la captura y libera recursos."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._cap:
            self._cap.release()
            self._cap = None
        log.info("Capturadora detenida")

    async def _read_loop(self):
        """Lee frames continuamente en background."""
        loop = asyncio.get_event_loop()
        while self.is_running and self._cap:
            try:
                # Leer en executor para no bloquear event loop
                ret, frame = await loop.run_in_executor(
                    None, self._cap.read
                )
                if ret and frame is not None:
                    # Aplicar correcciones de software (gamma, hist eq)
                    corrected = apply_software_correction(frame, self._cfg)
                    async with self._lock:
                        self._frame = corrected
                        self.frame_count += 1
                else:
                    await asyncio.sleep(0.01)
            except Exception as e:
                log.error(f"Error leyendo frame: {e}")
                await asyncio.sleep(0.1)

    async def get_frame(self) -> Optional[np.ndarray]:
        """Retorna el último frame capturado (BGR)."""
        async with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def update_config(self, cfg: dict) -> None:
        """Aplica nueva configuración al stream en curso sin reiniciarlo."""
        self._cfg = {**self._cfg, **cfg}
        if self._cap:
            self._cap.set(cv2.CAP_PROP_BRIGHTNESS,  self._cfg.get("brightness", 0))
            self._cap.set(cv2.CAP_PROP_CONTRAST,    self._cfg.get("contrast", 32))
            self._cap.set(cv2.CAP_PROP_SATURATION,  self._cfg.get("saturation", 60))

    @property
    def status(self) -> dict:
        return {
            "running":     self.is_running,
            "device_id":   self.device_id,
            "width":       self.width,
            "height":      self.height,
            "fps":         self.fps,
            "frame_count": self.frame_count,
        }


# ──────────────────────────────────────────────
# 3. WebRTC Video Track
# ──────────────────────────────────────────────

class FPVVideoTrack(MediaStreamTrack):
    """
    Track de video WebRTC alimentado por un frame_getter async.
    Desacoplado de VideoCapture para permitir insertar YOLO en el pipeline.
    """
    kind = "video"

    def __init__(self, frame_getter, width: int = 1280, height: int = 720, fps: float = 30):
        super().__init__()
        self._get_frame = frame_getter   # async callable → Optional[np.ndarray] BGR
        self._width     = width
        self._height    = height
        self._fps       = float(fps) or 30
        self._pts       = 0
        self._time_base = fractions.Fraction(1, 90000)

    async def recv(self) -> VideoFrame:
        frame_bgr = await self._get_frame()
        if frame_bgr is None:
            frame_bgr = np.zeros((self._height, self._width, 3), dtype=np.uint8)

        frame_rgb   = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")

        video_frame.pts       = self._pts
        video_frame.time_base = self._time_base
        self._pts += int(90000 / self._fps)

        await asyncio.sleep(1.0 / self._fps)
        return video_frame


# ──────────────────────────────────────────────
# 4. Video Recorder
# ──────────────────────────────────────────────

class VideoRecorder:
    """
    Graba el video de la capturadora en un archivo MP4,
    sincronizado con la sesión de telemetría activa.
    """

    def __init__(self):
        self._writer:     Optional[cv2.VideoWriter] = None
        self._session_id: Optional[str]             = None
        self._start_time: Optional[float]           = None
        self._frame_count = 0
        self.is_recording = False
        self.output_path: Optional[str]             = None

    def start(self, session_id: str,
              width: int, height: int, fps: float = 30.0) -> str:
        """Comienza la grabación."""
        if self.is_recording:
            self.stop()

        self._session_id = session_id
        self._start_time = time.time()
        self._frame_count = 0

        filename = f"video_{session_id}.mp4"
        path     = VIDEO_DIR / filename
        self.output_path = str(path)

        # Codec MP4 (H.264 via FFmpeg)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(
            self.output_path, fourcc, fps, (width, height)
        )

        if not self._writer.isOpened():
            # Fallback a AVI
            filename = f"video_{session_id}.avi"
            path     = VIDEO_DIR / filename
            self.output_path = str(path)
            fourcc  = cv2.VideoWriter_fourcc(*"XVID")
            self._writer = cv2.VideoWriter(
                self.output_path, fourcc, fps, (width, height)
            )

        self.is_recording = True
        log.info(f"Grabación iniciada: {self.output_path}")
        return self.output_path

    def write_frame(self, frame: np.ndarray) -> None:
        """Escribe un frame en el archivo."""
        if self._writer and self.is_recording and frame is not None:
            self._writer.write(frame)
            self._frame_count += 1

    def stop(self) -> Optional[str]:
        """Detiene la grabación y retorna el path del archivo."""
        if not self.is_recording:
            return None

        self.is_recording = False
        if self._writer:
            self._writer.release()
            self._writer = None

        duration = time.time() - self._start_time if self._start_time else 0
        size_mb  = 0
        if self.output_path:
            p = Path(self.output_path)
            if p.exists():
                size_mb = p.stat().st_size / (1024 * 1024)

        log.info(
            f"Grabación detenida: {self._frame_count} frames, "
            f"{duration:.1f}s, {size_mb:.1f} MB → {self.output_path}"
        )
        return self.output_path

    @property
    def status(self) -> dict:
        duration = (time.time() - self._start_time) if (self._recording and self._start_time) else 0
        return {
            "recording":    self.is_recording,
            "session_id":   self._session_id,
            "frame_count":  self._frame_count,
            "duration_s":   round(duration, 1),
            "output_path":  self.output_path,
        }

    @property
    def _recording(self):
        return self.is_recording


# ──────────────────────────────────────────────
# 5. WebRTC Manager
# ──────────────────────────────────────────────

class WebRTCManager:
    """
    Gestiona las conexiones WebRTC peer-to-peer.
    Recibe un frame_getter para desacoplarse de VideoCapture
    y permitir inyectar pasos intermedios (YOLO, overlay, etc.).
    """

    def __init__(self, frame_getter, width: int = 1280, height: int = 720, fps: float = 30):
        self._frame_getter = frame_getter
        self._width        = width
        self._height       = height
        self._fps          = float(fps) or 30
        self._peers:       Dict[str, RTCPeerConnection] = {}

    async def handle_offer(self, sdp: str, sdp_type: str, peer_id: str) -> dict:
        """
        Procesa un SDP offer del browser y retorna el SDP answer.
        """
        offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
        pc    = RTCPeerConnection()

        self._peers[peer_id] = pc

        track = FPVVideoTrack(self._frame_getter, self._width, self._height, self._fps)
        pc.addTrack(track)

        # Evento de cierre
        @pc.on("connectionstatechange")
        async def on_state_change():
            state = pc.connectionState
            log.info(f"[WebRTC] Peer {peer_id}: {state}")
            if state in ("failed", "closed", "disconnected"):
                await self._remove_peer(peer_id)

        # Procesar offer y generar answer
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return {
            "sdp":  pc.localDescription.sdp,
            "type": pc.localDescription.type,
        }

    async def _remove_peer(self, peer_id: str):
        """Cierra y elimina un peer."""
        pc = self._peers.pop(peer_id, None)
        if pc:
            await pc.close()
            log.info(f"[WebRTC] Peer {peer_id} eliminado")

    async def close_all(self):
        """Cierra todas las conexiones."""
        for pc in self._peers.values():
            await pc.close()
        self._peers.clear()

    @property
    def peer_count(self) -> int:
        return len(self._peers)

    @property
    def status(self) -> dict:
        return {
            "active_peers": self.peer_count,
            "peer_ids":     list(self._peers.keys()),
        }


# ──────────────────────────────────────────────
# 6. VideoStreamer (fachada unificada)
# ──────────────────────────────────────────────

class VideoStreamer:
    """
    Fachada que agrupa captura, YOLO, WebRTC y grabación.
    Pipeline de frames: captura → correcciones → [YOLO] → WebRTC / grabación
    """

    def __init__(self):
        self.capture  = VideoCapture()
        self.recorder = VideoRecorder()
        self.webrtc:  Optional[WebRTCManager] = None

        # YOLO (opcional — no falla si ultralytics no está instalado)
        try:
            from yolo_processor import YOLOProcessor
            self.yolo: Optional[YOLOProcessor] = YOLOProcessor()
            log.info("[VideoStreamer] YOLOProcessor disponible")
        except ImportError:
            self.yolo = None
            log.info("[VideoStreamer] yolo_processor no disponible (ultralytics no instalado)")

    async def _get_display_frame(self):
        """Frame getter para WebRTC: captura → [YOLO] → frame BGR."""
        frame = await self.capture.get_frame()
        if frame is not None and self.yolo and self.yolo.enabled:
            frame = await self.yolo.process_async(frame)
        return frame

    async def start_capture(self, device_id: int = 0,
                            width: int = 1280, height: int = 720,
                            fps: int = 30) -> bool:
        """Inicia la captura y habilita WebRTC."""
        ok = await self.capture.start(device_id, width, height, fps)
        if ok:
            self.webrtc = WebRTCManager(
                self._get_display_frame,
                self.capture.width,
                self.capture.height,
                self.capture.fps,
            )
            log.info("VideoStreamer listo")
        return ok

    async def stop_capture(self):
        """Detiene todo: captura, WebRTC y grabación."""
        if self.recorder.is_recording:
            self.recorder.stop()
        if self.webrtc:
            await self.webrtc.close_all()
            self.webrtc = None
        await self.capture.stop()

    async def handle_offer(self, sdp: str, sdp_type: str, peer_id: str) -> Optional[dict]:
        """Delega al WebRTC manager."""
        if not self.webrtc:
            return None
        return await self.webrtc.handle_offer(sdp, sdp_type, peer_id)

    def start_recording(self, session_id: str) -> Optional[str]:
        """Inicia la grabación sincronizada con una sesión de telemetría."""
        if not self.capture.is_running:
            return None
        path = self.recorder.start(
            session_id,
            self.capture.width,
            self.capture.height,
            self.capture.fps,
        )
        # Iniciar loop de grabación
        asyncio.create_task(self._record_loop())
        return path

    async def _record_loop(self):
        """Loop que escribe frames al archivo de video."""
        while self.recorder.is_recording:
            frame = await self.capture.get_frame()
            if frame is not None:
                self.recorder.write_frame(frame)
            await asyncio.sleep(1.0 / (self.capture.fps or 30))

    def stop_recording(self) -> Optional[str]:
        """Detiene la grabación."""
        return self.recorder.stop()

    @property
    def status(self) -> dict:
        return {
            "capture":  self.capture.status,
            "recorder": self.recorder.status,
            "webrtc":   self.webrtc.status if self.webrtc else {"active_peers": 0},
            "yolo":     self.yolo.status if self.yolo else {"available": False},
        }

    @staticmethod
    def list_devices() -> list:
        """Lista las capturadoras disponibles."""
        return DeviceManager.enumerate()


# ──────────────────────────────────────────────
# Test standalone
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test de capturadora USB")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width",  type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    print("=" * 60)
    print("  VideoStreamer — Test de captura")
    print("=" * 60)
    print()
    print("Enumerando dispositivos de captura...")
    devices = DeviceManager.enumerate()

    if not devices:
        print("⚠  No se encontraron dispositivos de video.")
        print("   Verifica que la capturadora USB esté conectada.")
        exit(1)

    print(f"✅ {len(devices)} dispositivo(s) encontrado(s):\n")
    for d in devices:
        print(f"  [{d['id']}] {d['name']} — {d['width']}x{d['height']} @ {d['fps']}fps")

    print()
    print(f"Abriendo dispositivo {args.device} a {args.width}x{args.height}...")
    print("Presiona Q para salir.")
    print()

    cap = cv2.VideoCapture(args.device, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print(f"❌ No se pudo abrir el dispositivo {args.device}")
        exit(1)

    import time
    prev_time = time.time()
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠  Sin frame")
            continue

        frame_count += 1
        now  = time.time()
        fps  = frame_count / (now - prev_time)

        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.putText(frame, f"Res: {args.width}x{args.height}", (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("FPV Capture Test", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Test finalizado.")
