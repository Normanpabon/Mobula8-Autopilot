"""
VideoStreamer — FPV Video Module
=================================
Captura video desde la capturadora USB (RCA), lo transmite via WebRTC
y graba MP4 sincronizado con las sesiones de telemetría.

Dependencias:
    pip install aiortc opencv-python

Uso independiente (test):
    python video_streamer.py --device 0 --width 720 --height 480
"""
import sys
import os
import asyncio
import concurrent.futures
import subprocess
import platform
import time
import logging
import math
import fractions
import json
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

import cv2
import numpy as np

from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from av import VideoFrame

log = logging.getLogger("video_streamer")

# logs/ vive en la raíz del repo; video_config.json junto a este módulo (backend/)
LOGS_DIR    = Path(__file__).resolve().parent.parent / "logs"
VIDEO_DIR   = LOGS_DIR / "video"
CONFIG_FILE = Path(__file__).parent / "video_config.json"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

IS_WINDOWS = platform.system() == "Windows"
NTSC_FPS = 30000 / 1001


def _open_capture(device_id: int) -> cv2.VideoCapture:
    """
    Abre la capturadora probando backends en orden de compatibilidad.
    OpenCV 4.8+ en Windows: MSMF es el backend fiable para apertura
    por índice; DSHOW queda como fallback.
    """
    if IS_WINDOWS:
        backends = [cv2.CAP_MSMF, cv2.CAP_DSHOW]
    elif sys.platform.startswith("linux"):
        backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
    else:
        backends = [cv2.CAP_ANY]
    for be in backends:
        cap = cv2.VideoCapture(device_id, be)
        if cap.isOpened():
            return cap
        cap.release()
    return cv2.VideoCapture(device_id)  # último recurso


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
        log_prefix = f"[Dispositivo {idx}]"
        logging.debug(f"{log_prefix} Iniciando prueba...")
        
        try:
            cap = _open_capture(idx)
            
            if not cap.isOpened():
                logging.warning(f"{log_prefix} Falló al abrir (isOpened == False). Causas: No existe, sin permisos, o backend no soportado.")
                return None
            
            logging.debug(f"{log_prefix} Abierto correctamente. Intentando leer frames...")
            
            frame_valid = False
            for i in range(10):
                ret, frame = cap.read()
                if ret and frame is not None:
                    logging.debug(f"{log_prefix} Frame válido recibido en el intento {i+1}")
                    frame_valid = True
                    break
                logging.debug(f"{log_prefix} Intento {i+1} fallido (ret={ret}, frame={'Válido' if frame is not None else 'Nulo'})")
                time.sleep(0.05)
                
            if not frame_valid:
                logging.warning(f"{log_prefix} Se agotaron los intentos para leer un frame. La capturadora no entrega imagen.")
                cap.release()
                return None
                
            name = DeviceManager.get_device_name(idx)
            logging.info(f"{log_prefix} Dispositivo detectado exitosamente: {name}")
            
            result = {
                "id":        idx,
                "name":      name,
                "width":     int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height":    int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps":       cap.get(cv2.CAP_PROP_FPS) or 30,
                "available": True,
            }
            cap.release()
            return result
            
        except Exception as e:
            logging.error(f"{log_prefix} Excepción inesperada: {str(e)}")
            return None

    @staticmethod
    def enumerate() -> list[dict]:
        logging.info("Iniciando enumeración de dispositivos (índices 0 al 9)...")
        devices = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futs = [executor.submit(DeviceManager._test_device, idx) for idx in range(10)]
            try:
                for fut in concurrent.futures.as_completed(futs, timeout=12):
                    try:
                        result = fut.result()
                        if result:
                            devices.append(result)
                    except Exception as e:
                        logging.error(f"Error en el hilo de enumeración: {str(e)}")
            except concurrent.futures.TimeoutError:
                logging.error("Timeout durante la enumeración de dispositivos.")
                
        logging.info(f"Enumeración finalizada. Dispositivos listos: {[d['id'] for d in devices]}")
        return sorted(devices, key=lambda d: d["id"])

    @staticmethod
    def get_device_name(idx: int) -> str:
        if sys.platform == "win32":
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_PnPEntity | "
                     "Where-Object { $_.PNPClass -in @('Camera','Image','Media') -and $_.Status -eq 'OK' } | "
                     "Select-Object -ExpandProperty Name"],
                    capture_output=True, text=True, timeout=8
                )
                names = [l.strip() for l in result.stdout.splitlines() if l.strip()]
                return names[idx] if idx < len(names) else f"Capture Device {idx}"
            except Exception:
                return f"Capture Device {idx}"
        else:
            sys_path = f"/sys/class/video4l/video{idx}/name"
            if os.path.exists(sys_path):
                try:
                    with open(sys_path, 'r') as f:
                        return f.read().strip()
                except Exception:
                    pass
            return f"Video Device {idx}"

# ──────────────────────────────────────────────
# 2. Video Capture (OpenCV)
# ──────────────────────────────────────────────

class VideoCapture:
    """Captura sin reescalar: el array recibido determina la geometría real."""

    def __init__(self):
        self._cap = None
        self._frame = None
        self._lock = asyncio.Lock()
        self._task = None
        self._cfg = load_video_config()
        self.is_running = False
        self.device_id = 0
        self.width, self.height = 720, 480
        self.fps = NTSC_FPS
        self.requested = {}
        self.fps_source = "requested"
        self.frame_count = 0
        self.measured_fps = 0.0
        self._last_frame_at = None
        self.error = None
        self.format_warning = None

    def _open_configured(self, device_id, width, height, fps):
        """Operaciones del driver fuera del event loop; algunos ignoran set()."""
        cap = _open_capture(device_id)
        try:
            if not cap.isOpened():
                raise RuntimeError(f"No se pudo abrir dispositivo {device_id}")
            for prop, value in (
                (cv2.CAP_PROP_FRAME_WIDTH, width),
                (cv2.CAP_PROP_FRAME_HEIGHT, height),
                (cv2.CAP_PROP_FPS, fps),
                (cv2.CAP_PROP_BUFFERSIZE, 1),
                (cv2.CAP_PROP_BRIGHTNESS, self._cfg.get("brightness", 0)),
                (cv2.CAP_PROP_CONTRAST, self._cfg.get("contrast", 32)),
                (cv2.CAP_PROP_SATURATION, self._cfg.get("saturation", 60)),
            ):
                cap.set(prop, value)
            for _ in range(10):
                ret, frame = cap.read()
                if ret and frame is not None and frame.size:
                    return cap, frame, cap.get(cv2.CAP_PROP_FPS)
                time.sleep(0.05)
            raise RuntimeError(f"Dispositivo {device_id} no devuelve frames")
        except Exception:
            cap.release()
            raise

    async def start(self, device_id: int = 0, width: int = 720,
                    height: int = 480, fps: Optional[float] = None) -> bool:
        await self.stop()
        self._cfg = load_video_config()
        target_fps = float(fps if fps is not None else
                           (NTSC_FPS if self._cfg.get("ntsc", True) else 25))
        if width <= 0 or height <= 0 or not math.isfinite(target_fps) or target_fps <= 0:
            raise ValueError("Resolución y FPS deben ser positivos y finitos")
        self.device_id = device_id
        self.requested = {"width": width, "height": height, "fps": target_fps}
        self.error = self.format_warning = None
        self.measured_fps = 0.0
        self.frame_count = 0
        try:
            cap, frame, driver_fps = await asyncio.to_thread(
                self._open_configured, device_id, width, height, target_fps)
        except Exception as exc:
            self.error = str(exc)
            log.error(self.error)
            return False
        self._cap = cap
        self.height, self.width = frame.shape[:2]
        valid_fps = math.isfinite(driver_fps) and 0 < driver_fps <= 240
        self.fps = float(driver_fps) if valid_fps else target_fps
        self.fps_source = "driver" if valid_fps else "requested_fallback"
        if (self.width, self.height) != (width, height) or abs(self.fps - target_fps) > 0.1:
            self.format_warning = (
                f"Pedido {width}×{height} @ {target_fps:.2f}; "
                f"capturadora entrega {self.width}×{self.height} @ {self.fps:.2f}")
            log.warning(self.format_warning)
        self._frame = apply_software_correction(frame, self._cfg)
        self._last_frame_at = time.monotonic()
        self.is_running = True
        self._task = asyncio.create_task(self._read_loop())
        log.info("Captura real: %sx%s @ %.3f FPS (%s)",
                 self.width, self.height, self.fps, self.fps_source)
        return True

    async def stop(self):
        self.is_running = False
        if self._task:
            # Esperar la lectura en curso antes de release: cancelar el await
            # no detiene un read() que ya corre en el executor.
            await self._task
            self._task = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._frame = None
        self._last_frame_at = None

    async def _read_loop(self):
        window_start, count = time.monotonic(), 0
        while self.is_running and self._cap is not None:
            try:
                ret, frame = await asyncio.to_thread(self._cap.read)
                if not self.is_running:
                    break
                if ret and frame is not None:
                    if frame.shape[:2] != (self.height, self.width):
                        raise RuntimeError("El formato cambió durante la captura; reinicia el stream")
                    corrected = apply_software_correction(frame, self._cfg)
                    async with self._lock:
                        self._frame = corrected
                        self.frame_count += 1
                        self._last_frame_at = time.monotonic()
                    count += 1
                    elapsed = self._last_frame_at - window_start
                    if elapsed >= 1:
                        self.measured_fps = count / elapsed
                        window_start, count = self._last_frame_at, 0
                else:
                    if time.monotonic() - self._last_frame_at > 2:
                        raise RuntimeError("Sin frames de la capturadora durante más de 2 s")
                    await asyncio.sleep(0.01)
            except Exception as exc:
                self.error = str(exc)
                self.is_running = False
                log.error("Captura detenida: %s", exc)

    async def get_frame(self) -> Optional[np.ndarray]:
        async with self._lock:
            fresh = self._last_frame_at is not None and time.monotonic() - self._last_frame_at < 2
            return self._frame.copy() if self.is_running and fresh and self._frame is not None else None

    def update_config(self, cfg: dict) -> None:
        self._cfg = {**self._cfg, **cfg}
        if self._cap is not None:
            self._cap.set(cv2.CAP_PROP_BRIGHTNESS, self._cfg.get("brightness", 0))
            self._cap.set(cv2.CAP_PROP_CONTRAST, self._cfg.get("contrast", 32))
            self._cap.set(cv2.CAP_PROP_SATURATION, self._cfg.get("saturation", 60))

    @property
    def status(self) -> dict:
        return {
            "running": self.is_running, "device_id": self.device_id,
            "width": self.width, "height": self.height, "fps": self.fps,
            "fps_source": self.fps_source, "requested": self.requested,
            "measured_fps": round(self.measured_fps, 2) if self.is_running else 0,
            "frame_count": self.frame_count, "error": self.error,
            "format_warning": self.format_warning,
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

    def __init__(self, frame_getter, width: int = 720, height: int = 480, fps: float = 30):
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
    """Una toma por archivo, con geometría igual a los frames capturados."""

    def __init__(self):
        self._writer = None
        self._session_id = None
        self._start_time = None
        self._duration = 0
        self._frame_count = 0
        self._size = None
        self.is_recording = False
        self.output_path = None
        self.error = None

    def start(self, session_id: str, width: int, height: int,
              fps: float = NTSC_FPS) -> str:
        if self.is_recording:
            return self.output_path
        self.error = None
        self.output_path = None
        self._frame_count = 0
        self._duration = 0
        self._session_id = session_id
        self._size = (width, height)
        take = uuid4().hex[:12]
        # mp4v = MPEG-4 Part 2. AVI/XVID es un fallback, no H.264.
        for ext, codec in (("mp4", "mp4v"), ("avi", "XVID")):
            path = VIDEO_DIR / f"video_{session_id}_{take}.{ext}"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, self._size)
            if writer.isOpened():
                self._writer = writer
                self.output_path = str(path)
                self._start_time = time.monotonic()
                self.is_recording = True
                return self.output_path
            writer.release()
        self.error = "No se pudo abrir ningún encoder de video (MP4/AVI)"
        raise RuntimeError(self.error)

    def write_frame(self, frame: np.ndarray) -> None:
        if self._writer is None or not self.is_recording:
            return
        if frame is None or (frame.shape[1], frame.shape[0]) != self._size:
            self.error = "El tamaño del frame no coincide con el de la grabación"
            raise RuntimeError(self.error)
        self._writer.write(frame)
        self._frame_count += 1

    def stop(self) -> Optional[str]:
        if not self.is_recording:
            return self.output_path
        self.is_recording = False
        self._duration = time.monotonic() - self._start_time
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        if self._frame_count == 0:
            self.error = self.error or "La toma terminó sin frames; archivo no validado"
        log.info("Grabación cerrada: %s frames → %s", self._frame_count, self.output_path)
        return self.output_path

    @property
    def status(self) -> dict:
        duration = time.monotonic() - self._start_time if self.is_recording else self._duration
        return {
            "recording": self.is_recording, "session_id": self._session_id,
            "frame_count": self._frame_count, "duration_s": round(duration, 1),
            "output_path": self.output_path, "error": self.error,
        }


# ──────────────────────────────────────────────
# 5. WebRTC Manager
# ──────────────────────────────────────────────

class WebRTCManager:
    """
    Gestiona las conexiones WebRTC peer-to-peer.
    Recibe un frame_getter para desacoplarse de VideoCapture
    y permitir inyectar pasos intermedios (YOLO, overlay, etc.).
    """

    def __init__(self, frame_getter, width: int = 720, height: int = 480, fps: float = 30):
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
    Fachada que agrupa captura, visión (segmentación + YOLO), WebRTC y grabación.
    Pipeline de frames: captura → correcciones → overlay de visión → WebRTC / grabación.
    La inferencia corre desacoplada en VisionPipeline (loop propio); el stream
    solo dibuja el último resultado publicado, sin esperar a la inferencia.
    """

    def __init__(self):
        self.capture  = VideoCapture()
        self.recorder = VideoRecorder()
        self.webrtc:  Optional[WebRTCManager] = None
        self._record_task = None
        self._lifecycle_lock = asyncio.Lock()

        # Visión (opcional — no falla si ultralytics no está instalado;
        # los procesadores reportan available=False y los endpoints responden 503)
        try:
            from vision_pipeline import VisionPipeline
            self.vision: Optional[VisionPipeline] = VisionPipeline()
            log.info("[VideoStreamer] VisionPipeline disponible")
        except Exception as e:
            self.vision = None
            log.warning(f"[VideoStreamer] vision_pipeline no disponible: {e}")

    @property
    def yolo(self):
        """Alias de compatibilidad (endpoints /api/yolo/*): el detector del pipeline."""
        return self.vision.detector if self.vision else None

    async def _get_display_frame(self):
        """Frame getter para WebRTC: captura → overlay de visión (no bloqueante)."""
        frame = await self.capture.get_frame()
        if frame is not None and self.vision:
            frame = self.vision.annotate(frame)
        return frame

    async def start_capture(self, device_id: int = 0,
                            width: int = 720, height: int = 480,
                            fps: Optional[float] = None) -> bool:
        async with self._lifecycle_lock:
            requested = self.capture.requested
            if (self.capture.is_running and device_id == self.capture.device_id
                    and width == requested.get("width") and height == requested.get("height")
                    and (fps is None or fps == requested.get("fps"))):
                return True  # Reconectar un navegador no reinicia captura/grabación.
            if self.recorder.is_recording:
                raise RuntimeError("Detén la grabación antes de cambiar la captura")
            await self._stop_capture()
            ok = await self.capture.start(device_id, width, height, fps)
            if ok:
                self.webrtc = WebRTCManager(self._get_display_frame,
                    self.capture.width, self.capture.height, self.capture.fps)
                if self.vision:
                    self.vision.start(self.capture.get_frame)
            return ok

    async def _stop_recording(self):
        if self._record_task:
            self._record_task.cancel()
            try:
                await self._record_task
            except asyncio.CancelledError:
                pass
            self._record_task = None
        return self.recorder.stop()

    async def _stop_capture(self):
        await self._stop_recording()
        if self.vision:
            await self.vision.stop()
        if self.webrtc:
            await self.webrtc.close_all()
            self.webrtc = None
        await self.capture.stop()

    async def stop_capture(self):
        async with self._lifecycle_lock:
            await self._stop_capture()

    async def handle_offer(self, sdp: str, sdp_type: str, peer_id: str) -> Optional[dict]:
        if not self.webrtc:
            return None
        return await self.webrtc.handle_offer(sdp, sdp_type, peer_id)

    async def start_recording(self, session_id: str) -> str:
        async with self._lifecycle_lock:
            if self.recorder.is_recording:
                return self.recorder.output_path
            frame = await self.capture.get_frame()
            if frame is None:
                raise RuntimeError("No hay un frame reciente para grabar")
            path = self.recorder.start(session_id, frame.shape[1], frame.shape[0], self.capture.fps)
            self._record_task = asyncio.create_task(self._record_loop())
            return path

    async def _record_loop(self):
        deadline = time.monotonic()
        try:
            while self.recorder.is_recording:
                frame = await self.capture.get_frame()
                if frame is None:
                    raise RuntimeError("Grabación detenida: no hay video reciente")
                self.recorder.write_frame(frame)
                deadline += 1.0 / self.capture.fps
                now = time.monotonic()
                if deadline < now:
                    deadline = now
                await asyncio.sleep(max(0, deadline - now))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.recorder.error = str(exc)
            log.error("Grabación: %s", exc)
        finally:
            self.recorder.stop()

    async def stop_recording(self) -> Optional[str]:
        async with self._lifecycle_lock:
            return await self._stop_recording()

    @property
    def status(self) -> dict:
        return {
            "capture":  self.capture.status,
            "recorder": self.recorder.status,
            "webrtc":   self.webrtc.status if self.webrtc else {"active_peers": 0},
            "vision":   self.vision.status if self.vision else {"available": False},
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
    parser.add_argument("--width",  type=int, default=720)
    parser.add_argument("--height", type=int, default=480)
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

    cap = _open_capture(args.device)
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
        cv2.putText(frame, f"Res: {frame.shape[1]}x{frame.shape[0]}", (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("FPV Capture Test", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Test finalizado.")
