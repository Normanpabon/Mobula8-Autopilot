"""
ELRS Backend WebSocket Server v2.7.1
"""
import asyncio, json, argparse
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections import deque
from typing import Optional, List, Literal
import struct
import time
import platform
import re
import logging
import subprocess
import sys

from app_logging import LEVELS, config_from_env_and_argv, configure_logging, run_id

APP_LOG_CONFIG = config_from_env_and_argv()
APP_LOG_PATH = configure_logging(APP_LOG_CONFIG)
log = logging.getLogger("app")

import serial
from serial.tools import list_ports
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request as FRequest
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator, StrictBool
import uvicorn

from session_manager import SessionManager
from command_injector import CommandInjector
from serial_manager import SerialManager

CRSF_SYNC = 0xEA

# Tabla CRC8 DVB-S2 precomputada una sola vez al importar el módulo
# (se consulta por cada frame CRSF recibido, cientos de veces por segundo)
_CRC_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = ((_c<<1)^0xD5)&0xFF if (_c&0x80) else (_c<<1)&0xFF
    _CRC_TABLE.append(_c)

def crc8_dvb_s2(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = _CRC_TABLE[crc ^ b]
    return crc

def parse_crsf_frame(raw: bytes) -> Optional[dict]:
    if len(raw) < 4: return None
    ftype, payload = raw[2], raw[3:-1]
    if crc8_dvb_s2(raw[2:-1]) != raw[-1]: return None

    if ftype == 0x14 and len(payload) >= 10:
        return {"type": "link", "data": {
            "rssi1": struct.unpack("b", bytes([payload[0]]))[0],
            "rssi2": struct.unpack("b", bytes([payload[1]]))[0],
            "lq": payload[2],
            "snr": struct.unpack("b", bytes([payload[3]]))[0],
            "active_antenna": payload[4], "rf_mode": payload[5], "tx_power": payload[6],
            "uplink_rssi": struct.unpack("b", bytes([payload[7]]))[0],
            "uplink_lq": payload[8],
            "uplink_snr": struct.unpack("b", bytes([payload[9]]))[0],
        }}
    if ftype == 0x08 and len(payload) >= 8:
        return {"type": "battery", "data": {
            "voltage": struct.unpack(">H", payload[0:2])[0] / 10.0,
            "current": struct.unpack(">H", payload[2:4])[0] / 10.0,
            "mah_used": struct.unpack(">I", payload[4:8])[0] >> 8,
            "percent": payload[7],
        }}
    if ftype == 0x1E and len(payload) >= 6:
        r2d = 180 / 3.14159265359
        return {"type": "attitude", "data": {
            "pitch": round(struct.unpack(">h", payload[0:2])[0] / 10000 * r2d, 2),
            "roll":  round(struct.unpack(">h", payload[2:4])[0] / 10000 * r2d, 2),
            "yaw":   round(struct.unpack(">h", payload[4:6])[0] / 10000 * r2d, 2),
        }}
    if ftype == 0x21:
        return {"type": "flight_mode", "data": {"mode": payload.rstrip(b"\x00").decode("ascii","ignore")}}
    return None

class ConnectionManager:
    def __init__(self): self.active_connections: List[WebSocket] = []
    async def connect(self, ws: WebSocket):
        await ws.accept(); self.active_connections.append(ws)
        log.info("WebSocket telemetría conectado clients=%s", len(self.active_connections))
    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)
            log.info("WebSocket telemetría desconectado clients=%s", len(self.active_connections))
    async def broadcast(self, msg: dict):
        if not self.active_connections: return
        j = json.dumps(msg)
        await asyncio.gather(*[self._send(c, j) for c in self.active_connections], return_exceptions=True)
    async def _send(self, ws: WebSocket, msg: str):
        try: await ws.send_text(msg)
        except Exception:
            log.exception("Error enviando telemetría por WebSocket")
            self.disconnect(ws)

# ──────────────────────────────────────────────────────────────
# Lifespan (reemplaza @app.on_event, deprecated en FastAPI)
# ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global session
    system_status["start_time"] = datetime.now(timezone.utc)
    session = SessionManager()
    system_status["current_session_id"] = session.session_id
    session.save(finalize=False)  # También conserva las sesiones que nunca reciben telemetría.
    checkpoint_task = asyncio.create_task(session_checkpoints())
    try:
        revision = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                  cwd=Path(__file__).resolve().parent.parent,
                                  capture_output=True, text=True, timeout=1, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        revision = "unknown"
    log.info("Servidor iniciado run_id=%s version=2.7.1 revision=%s python=%s platform=%s log_level=%s log_file=%s vision_mode=%s",
             run_id(), revision, sys.version.split()[0], platform.platform(), APP_LOG_CONFIG.level,
             APP_LOG_PATH, video.vision.config.pipeline_mode if video and video.vision else "unavailable")
    if video and video.vision:
        log.debug("Configuración efectiva de visión: %s", video.vision.config.model_dump())
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None, help="Puerto inicial opcional; seleccionable desde la interfaz")
    parser.add_argument("--baud", type=int, default=115200)
    args, _ = parser.parse_known_args()
    if args.port:
        try:
            await connect_serial(SerialConnectRequest(port=args.port, baud=args.baud))
        except Exception as exc:
            system_status["serial_error"] = str(exc)
            log.exception("No se pudo conectar el puerto inicial")
    injector.start()
    log.info("ELRS Telemetry Server v2.7.1 listo")
    try:
        yield
    finally:
        checkpoint_task.cancel()
        try:
            await checkpoint_task
        except asyncio.CancelledError:
            pass
        await serial_manager.disconnect()
        await injector.stop()
        if video:
            await video.stop_capture()
        if session:
            session.save()
        log.info("Servidor detenido run_id=%s", run_id())


async def session_checkpoints():
    """Atomic snapshots limit telemetry loss after an unclean exit."""
    last = (None, None)
    while True:
        await asyncio.sleep(10)
        current = session
        if current and (current.session_id, current.current_frame_count) != last:
            try:
                await asyncio.to_thread(current.save, finalize=False)
                last = (current.session_id, current.current_frame_count)
            except Exception:
                log.exception("No se pudo guardar checkpoint de sesión")

app = FastAPI(title="ELRS Telemetry Server", version="2.7.1", lifespan=lifespan)


@app.middleware("http")
async def log_http(request: FRequest, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("HTTP %s %s falló", request.method, request.url.path)
        raise
    log.debug("HTTP %s %s status=%s duration_ms=%.1f", request.method,
              request.url.path, response.status_code, (time.perf_counter() - start) * 1000)
    return response
manager = ConnectionManager()
session: Optional[SessionManager] = None
telemetry_history = deque(maxlen=500)
system_status = {"serial_port": None, "baud_rate": None, "connected": False, "serial_error": None,
                 "frames_received": 0, "uptime_seconds": 0, "start_time": None,
                 "current_session_id": None, "current_session_frames": 0,
                 "serial_bytes_received": 0, "serial_sync_discarded": 0,
                 "serial_crc_errors": 0, "serial_unknown_frames": 0,
                 "serial_valid_frames": 0, "last_serial_byte_at": None,
                 "last_crsf_frame_at": None, "last_telemetry_at": None,
                 "frames_by_type": {}, "serial_unknown_types": {},
                 "serial_discarded_heads": {}}

injector = CommandInjector(write_fn=lambda frame: serial_manager.write(frame))
serial_buffer = bytearray()
_last_telemetry_mono = None
_next_serial_sample_mono = 0.0


def serial_lost():
    global _last_telemetry_mono
    injector.enabled = False
    injector.reset()
    serial_buffer.clear()
    _last_telemetry_mono = None
    log.info("Flujo serial interrumpido; inyección RC deshabilitada")


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ──────────────────────────────────────────────────────────────
# VIDEO — Import (antes de las rutas para evitar que el catch-all
#         de frontend bloquee GET /api/video/*)
# ──────────────────────────────────────────────────────────────
try:
    from video_streamer import VideoStreamer, CONFIG_FILE, load_video_config, profile_config
    video = VideoStreamer()
    VIDEO_AVAILABLE = True
    log.info("Módulo de video cargado")
except Exception as e:
    # Exception genérico (no solo ImportError): un error de carga en
    # video_streamer.py debe desactivar el módulo de video, no tumbar el server
    VIDEO_AVAILABLE = False
    video = None
    CONFIG_FILE = None
    load_video_config = None
    log.exception("Módulo de video no disponible: %s", e)


# ──────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────
class VideoStartRequest(BaseModel):
    device_id: int   = 0
    profile: Literal["analog", "digital"] = "digital"
    standard: Literal["ntsc", "pal"] = "ntsc"
    width: Optional[int] = Field(default=None, gt=0, le=1920)
    height: Optional[int] = Field(default=None, gt=0, le=1080)
    fps: Optional[float] = Field(default=None, gt=0, le=240, allow_inf_nan=False)

    @model_validator(mode="after")
    def paired_dimensions(self):
        if (self.width is None) != (self.height is None):
            raise ValueError("Especifica ancho y alto juntos")
        return self

class VideoConfigRequest(BaseModel):
    profile: Literal["analog", "digital"] = "analog"
    brightness: Optional[int] = None
    contrast: Optional[int] = None
    saturation: Optional[int] = None
    gamma:      float = 1.0
    hist_eq:    bool  = False
    wb_r:       float = 1.0
    wb_g:       float = 1.0
    wb_b:       float = 1.0

class YOLOConfigRequest(BaseModel):
    enabled:    bool  = False
    model:      str   = "yolo26n.pt"
    confidence: float = 0.5
    imgsz:      int   = 640     # 416/320 pueden reducir latencia; medir en el equipo objetivo

class SegmentationConfigRequest(BaseModel):
    enabled:    bool  = False
    model:      str   = "yolo26n-seg.pt"
    confidence: float = 0.35
    focus_mode: str   = "mask"  # Compatibilidad; no aplica preprocesamiento SEG→DET
    imgsz:      int   = 416

class VisionROIRequest(BaseModel):
    cells: List[StrictBool] = Field(min_length=96, max_length=96)


class GovernorConfigRequest(BaseModel):
    safety_distance_m: float = 3.0
    reaction_time_ms:  float = 250.0

class RCConfigRequest(BaseModel):
    enabled:    bool  = False
    rate_hz:    float = 50.0
    deadman_ms: float = 500.0
    sync_byte:  str   = "0xEE"   # 0xEE módulo TX | 0xEA radio | 0xC8 FC (validación de protocolo)

class RCChannelsRequest(BaseModel):
    epoch: Optional[str] = None
    channels: dict   # {"1": 1500, ..., "roll"/"pitch"/"throttle"/"yaw": µs}


# ──────────────────────────────────────────────────────────────
# Serial reader
# ──────────────────────────────────────────────────────────────
class SerialConnectRequest(BaseModel):
    port: str = Field(min_length=1, max_length=256)
    baud: int = Field(default=115200, ge=300, le=4000000)


class ClientEvent(BaseModel):
    level: Literal["info", "warning", "error"]
    message: str = Field(min_length=1, max_length=2000)


def available_serial_ports():
    ports = []
    aliases = sorted(Path('/dev/serial/by-id').glob('*')) if platform.system() == 'Linux' else []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        stable = next((str(alias) for alias in aliases if alias.resolve() == Path(p.device).resolve()), p.device)
        ports.append({"device": stable, "description": p.description or p.device, "path": p.device})
    return ports


def validate_serial_port(port):
    os_name = platform.system()
    if os_name == "Windows":
        port = port.upper()
        valid = re.fullmatch(r"COM[1-9][0-9]*", port)
    else:
        valid = port.startswith("/dev/") and ".." not in port.split("/")
    if not valid:
        raise ValueError(f"Puerto inválido para {os_name}: {port}")
    for item in available_serial_ports():
        if port in (item["device"], item["path"]):
            return item["device"]
    raise ValueError(f"Puerto no disponible: {port}. Actualiza la lista de puertos.")


@app.get("/api/serial/ports")
async def get_serial_ports():
    return {"platform": platform.system(), "ports": available_serial_ports()}


@app.post("/api/serial/connect")
async def connect_serial(req: SerialConnectRequest):
    async with serial_manager.lock:
        try:
            port = validate_serial_port(req.port.strip())
        except ValueError as exc:
            log.warning("Puerto serial rechazado port=%s reason=%s", req.port, exc)
            return JSONResponse({"error": str(exc)}, status_code=400)
        await serial_manager.disconnect()
        if session:
            session.save()
            start_new_session()
        connected = await serial_manager.connect(port, req.baud)
        telemetry_history.clear()
        for key in ("serial_bytes_received", "serial_sync_discarded", "serial_crc_errors",
                    "serial_unknown_frames", "serial_valid_frames", "frames_received"):
            system_status[key] = 0
        for key in ("last_serial_byte_at", "last_crsf_frame_at", "last_telemetry_at"):
            system_status[key] = None
        for key in ("frames_by_type", "serial_unknown_types", "serial_discarded_heads"):
            system_status[key] = {}
        return JSONResponse({"connected": connected, "serial_port": port,
                             "baud_rate": req.baud, "retrying": not connected,
                             "error": system_status['serial_error']}, status_code=200 if connected else 202)


@app.post("/api/serial/disconnect")
async def disconnect_serial():
    async with serial_manager.lock:
        await serial_manager.disconnect()
        if session:
            session.save()
            start_new_session()
        return {"connected": False}


def start_new_session():
    global session
    session = SessionManager()
    system_status["current_session_id"] = session.session_id
    system_status["current_session_frames"] = 0
    session.save(finalize=False)


def _sample_serial(reason, data):
    """Rate-limited bytes for diagnosing wrong port/mode without dumping a stream."""
    global _next_serial_sample_mono
    now = time.monotonic()
    if now >= _next_serial_sample_mono:
        log.debug("Serial descartado reason=%s sample_hex=%s", reason, bytes(data[:16]).hex(" "))
        _next_serial_sample_mono = now + 10


async def serial_data(data):
    global _last_telemetry_mono
    buf = serial_buffer
    system_status["serial_bytes_received"] += len(data)
    system_status["last_serial_byte_at"] = datetime.now(timezone.utc).isoformat()
    if system_status["serial_bytes_received"] == len(data):
        log.info("Primeros bytes seriales port=%s count=%s sample_hex=%s",
                 system_status["serial_port"], len(data), bytes(data[:16]).hex(" "))
    buf.extend(data)
    while buf:
        if buf[0] != CRSF_SYNC or (len(buf) >= 2 and not 2 <= buf[1] <= 62):
            system_status["serial_sync_discarded"] += 1
            head = f"0x{buf[0]:02X}"
            heads = system_status["serial_discarded_heads"]
            heads[head] = heads.get(head, 0) + 1
            _sample_serial("sync_or_length", buf)
            del buf[0]
            continue
        if len(buf) < 2:
            break
        total_len = buf[1] + 2
        if len(buf) < total_len:
            break
        frame = bytes(buf[:total_len])
        del buf[:total_len]
        if crc8_dvb_s2(frame[2:-1]) != frame[-1]:
            system_status["serial_crc_errors"] += 1
            _sample_serial("crc", frame)
            continue
        system_status["serial_valid_frames"] += 1
        system_status["last_crsf_frame_at"] = datetime.now(timezone.utc).isoformat()
        parsed = parse_crsf_frame(frame)
        if parsed:
            ts = datetime.now(timezone.utc).isoformat()
            _last_telemetry_mono = time.monotonic()
            system_status["last_telemetry_at"] = ts
            fd = {"timestamp": ts, **parsed}
            telemetry_history.append(fd)
            system_status["frames_received"] += 1
            types = system_status["frames_by_type"]
            types[parsed["type"]] = types.get(parsed["type"], 0) + 1
            log.debug("Telemetría recibida type=%s data=%s", parsed["type"], parsed["data"])
            if session:
                session.record(parsed["type"], parsed["data"], ts)
                system_status["current_session_frames"] = session.current_frame_count
            await manager.broadcast(fd)
        else:
            system_status["serial_unknown_frames"] += 1
            ftype = f"0x{frame[2]:02X}"
            unknown = system_status["serial_unknown_types"]
            unknown[ftype] = unknown.get(ftype, 0) + 1
            _sample_serial(f"frame_type_{frame[2]:02x}", frame)


serial_manager = SerialManager(system_status, available_serial_ports, serial_data, serial_lost)


# ──────────────────────────────────────────────────────────────
# Telemetry routes
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("WebSocket de telemetría terminó inesperadamente")
    finally:
        manager.disconnect(ws)

@app.get("/api/status")
async def get_status():
    if system_status["start_time"]:
        system_status["uptime_seconds"] = int((datetime.now(timezone.utc) - system_status["start_time"]).total_seconds())
    age_ms = round((time.monotonic() - _last_telemetry_mono) * 1000) if _last_telemetry_mono is not None else None
    active = bool(system_status["connected"] and age_ms is not None and age_ms <= 5000)
    telemetry_state = ("ACTIVE" if active else "STALE" if system_status["connected"] and age_ms is not None
                       else "WAITING" if system_status["connected"] else "DISCONNECTED")
    return JSONResponse({**system_status,
                         "start_time": system_status["start_time"].isoformat() if system_status["start_time"] else None,
                         "telemetry_active": active, "telemetry_state": telemetry_state,
                         "telemetry_age_ms": age_ms, "ws_clients": len(manager.active_connections),
                         "run_id": run_id(), "app_log_level": APP_LOG_CONFIG.level})


@app.post("/api/client/events")
async def client_event(event: ClientEvent):
    level = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}[event.level]
    logging.getLogger("frontend").log(level, "%s", event.message.replace("\r", "\\r").replace("\n", "\\n"))
    return {"recorded": APP_LOG_CONFIG.level != "OFF"}

@app.get("/api/history")
async def get_history(limit: int = 100):
    return JSONResponse({"frames": list(telemetry_history)[-limit:], "total": len(telemetry_history)})

@app.get("/api/latest")
async def get_latest():
    latest = {}
    for f in reversed(telemetry_history):
        if f["type"] not in latest: latest[f["type"]] = f
        if len(latest) >= 4: break
    return JSONResponse(latest)

@app.get("/api/sessions")
async def list_sessions():
    sessions = [item for item in SessionManager.list_sessions()
                if not session or item["session_id"] != session.session_id]
    current = None
    if session:
        current = {"session_id": session.session_id, "start_time": session.start_time.isoformat(),
                   "end_time": None, "live": True,
                   "summary": {"total_frames": session.current_frame_count,
                               "duration_seconds": round(session.current_duration, 1)}}
    return JSONResponse({"sessions": sessions, "current": current, "total": len(sessions)})

@app.get("/api/sessions/{session_id}/summary")
async def get_session_summary(session_id: str):
    doc = SessionManager.get_session(session_id)
    if not doc: return JSONResponse({"error": "No encontrada"}, status_code=404)
    light = {k: v for k, v in doc.items() if k != "frames"}
    light["frame_count"] = len(doc.get("frames", []))
    return JSONResponse(light)

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    doc = SessionManager.get_session(session_id)
    if not doc: return JSONResponse({"error": "No encontrada"}, status_code=404)
    return JSONResponse(doc)

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    ok = SessionManager.delete_session(session_id)
    if not ok: return JSONResponse({"error": "No encontrada"}, status_code=404)
    return JSONResponse({"deleted": session_id})

@app.post("/api/sessions/save")
async def save_and_new():
    global session
    if not session:
        return JSONResponse({"error": "Sin sesión"}, status_code=400)
    path = session.save(); saved_id = session.session_id
    start_new_session()
    return JSONResponse({"saved": saved_id, "path": path, "new_session": session.session_id})


# ──────────────────────────────────────────────────────────────
# Video routes
# IMPORTANTE: Deben estar ANTES del catch-all /{full_path:path}
# ──────────────────────────────────────────────────────────────
@app.get("/api/video/devices")
async def list_video_devices():
    if not VIDEO_AVAILABLE:
        return JSONResponse({"error": "Módulo de video no disponible", "devices": []})
    loop = asyncio.get_event_loop()
    devices = await loop.run_in_executor(None, VideoStreamer.list_devices)
    return JSONResponse({"devices": devices, "count": len(devices)})

@app.get("/api/video/status")
async def get_video_status():
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"available": False})
    return JSONResponse({"available": True, **video.status})

@app.get("/api/video/config")
async def get_video_config(profile: Literal["analog", "digital"] = "analog"):
    if not VIDEO_AVAILABLE or not load_video_config:
        return JSONResponse({"brightness": 0, "contrast": 32, "saturation": 60,
                             "gamma": 1.0, "hist_eq": False,
                             "wb_r": 1.0, "wb_g": 1.0, "wb_b": 1.0})
    return JSONResponse(profile_config(profile))

@app.post("/api/video/config")
async def update_video_config(req: VideoConfigRequest):
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Módulo de video no disponible"}, status_code=503)
    cfg = {
        "brightness": req.brightness,
        "contrast":   req.contrast,
        "saturation": req.saturation,
        "gamma":      req.gamma,
        "hist_eq":    req.hist_eq,
        "wb_r":       req.wb_r,
        "wb_g":       req.wb_g,
        "wb_b":       req.wb_b,
    }
    cfg = {key: value for key, value in cfg.items() if value is not None}
    if CONFIG_FILE and load_video_config:
        existing = load_video_config()
        if req.profile == "digital":
            existing["digital"] = {**existing.get("digital", {}), **cfg}
        else:
            existing.update(cfg)
        with open(CONFIG_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    if video.capture.is_running and video.capture.profile == req.profile:
        video.capture.update_config(cfg)
    log.info("Configuración de video actualizada profile=%s values=%s", req.profile, cfg)
    return JSONResponse({"updated": True, "config": cfg})

@app.post("/api/video/start")
async def start_video(req: VideoStartRequest):
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Módulo de video no disponible"}, status_code=503)
    try:
        ok = await video.start_capture(req.device_id, req.width, req.height, req.fps, req.profile, req.standard)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    if not ok:
        log.error("Captura falló device=%s profile=%s: %s", req.device_id, req.profile, video.capture.error)
        return JSONResponse({"error": f"No se pudo abrir dispositivo {req.device_id}"}, status_code=500)
    log.info("Captura iniciada device=%s profile=%s standard=%s actual=%sx%s fps=%.2f fourcc=%s",
             req.device_id, req.profile, req.standard, video.capture.width, video.capture.height,
             video.capture.fps, video.capture.pixel_format)
    log.debug("Negociación de captura: %s", video.capture.negotiation)
    return JSONResponse({"started": True, **video.capture.status})

@app.post("/api/video/stop")
async def stop_video():
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Módulo de video no disponible"}, status_code=503)
    await video.stop_capture()
    log.info("Captura detenida")
    return JSONResponse({"stopped": True})

@app.post("/api/video/recording/start")
async def start_recording():
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Módulo de video no disponible"}, status_code=503)
    if not video.capture.is_running:
        return JSONResponse({"error": "Captura no iniciada"}, status_code=400)
    sid = session.session_id if session else datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    try:
        path = await video.start_recording(sid)
    except RuntimeError as exc:
        log.exception("No se pudo iniciar grabación")
        return JSONResponse({"error": str(exc), "recording": False}, status_code=500)
    log.info("Grabación iniciada session_id=%s file=%s", sid, path)
    return JSONResponse({"recording": True, "session_id": video.recorder.status["session_id"], "path": path})

@app.post("/api/video/recording/stop")
async def stop_recording():
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Módulo de video no disponible"}, status_code=503)
    path = await video.stop_recording()
    log.info("Grabación detenida file=%s frames=%s error=%s", path,
             video.recorder.status["frame_count"], video.recorder.error)
    return JSONResponse({"recording": False, "saved": path, "error": video.recorder.error})

# ──────────────────────────────────────────────────────────────
# Vision routes (OFF / DETECT / SEGMENT + governor)
# ──────────────────────────────────────────────────────────────
@app.get("/api/vision/status")
async def get_vision_status():
    if not VIDEO_AVAILABLE or not video or not video.vision:
        return JSONResponse({"available": False})
    return JSONResponse(video.vision.status)

@app.get("/api/vision/roi")
async def get_vision_roi():
    if not VIDEO_AVAILABLE or not video or not video.vision:
        return JSONResponse({"error": "Visión no disponible"}, status_code=503)
    return JSONResponse(video.vision.roi_status)


@app.post("/api/vision/roi")
async def update_vision_roi(req: VisionROIRequest):
    if not VIDEO_AVAILABLE or not video or not video.vision:
        return JSONResponse({"error": "Visión no disponible"}, status_code=503)
    try:
        return JSONResponse(video.vision.set_roi(req.cells))
    except OSError:
        return JSONResponse({"error": "No se pudo guardar el área de visión"}, status_code=500)


@app.get("/api/vision/models")
async def list_vision_models():
    det_defaults = ["yolo26n.pt", "yolo26s.pt", "yolo26m.pt"]
    seg_defaults = ["yolo26n-seg.pt", "yolo26s-seg.pt"]
    if not VIDEO_AVAILABLE or not video or not video.vision:
        return JSONResponse({"detection":    {"custom": [], "defaults": det_defaults},
                             "segmentation": {"custom": [], "defaults": seg_defaults}})
    from vision_model import VisionModel
    return JSONResponse({
        "detection":    {"custom": VisionModel.list_local_models("detect"),
                         "defaults": det_defaults},
        "segmentation": {"custom": VisionModel.list_local_models("segment"),
                         "defaults": seg_defaults},
    })

@app.get("/api/vision/config")
async def get_vision_config():
    if not VIDEO_AVAILABLE or not video or not video.vision:
        return JSONResponse({"error": "Visión no disponible"}, status_code=503)
    return JSONResponse(video.vision.config.model_dump())


@app.post("/api/vision/config")
async def update_vision_config(req: dict):
    if not VIDEO_AVAILABLE or not video or not video.vision:
        return JSONResponse({"error": "Visión no disponible"}, status_code=503)
    try:
        config = await video.vision.configure(req)
        log.info("Visión configurada mode=%s model=%s imgsz=%s", config["pipeline_mode"],
                 config["models"].get(config["pipeline_mode"]) if config["pipeline_mode"] != "off" else None,
                 config["imgsz"])
        return JSONResponse({"updated": True, **config})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except Exception as exc:
        log.exception("No se pudo configurar visión")
        return JSONResponse({"error": f"No se pudo configurar visión: {exc}"}, status_code=503)


@app.post("/api/segmentation/config")
async def update_segmentation_config(req: SegmentationConfigRequest):
    # Legacy callers select an exclusive mode too; no independent stage switches.
    if req.focus_mode not in ('mask', 'overlay'):
        return JSONResponse({"error": "focus_mode inválido"}, status_code=422)
    return await update_vision_config({
        "pipeline_mode": "segment" if req.enabled else "off",
        "models": {"segment": req.model}, "imgsz": {"segment": req.imgsz},
        "confidence": {"default": req.confidence}})

@app.post("/api/vision/governor")
async def update_vision_governor(req: GovernorConfigRequest):
    if not VIDEO_AVAILABLE or not video or not video.vision:
        return JSONResponse({"error": "Visión no disponible"}, status_code=503)
    gov = video.vision.governor
    gov.safety_distance_m = req.safety_distance_m
    gov.reaction_time_ms  = req.reaction_time_ms
    return JSONResponse({"updated": True, **video.vision.status["governor"]})

# ── YOLO (detector) — rutas históricas, siguen siendo el contrato del panel AI
@app.get("/api/yolo/status")
async def get_yolo_status():
    if not VIDEO_AVAILABLE or not video or not video.yolo:
        return JSONResponse({"available": False})
    return JSONResponse(video.vision.status["detection"])

@app.get("/api/yolo/models")
async def list_yolo_models():
    if not VIDEO_AVAILABLE or not video or not video.yolo:
        return JSONResponse({"custom": [], "defaults": ["yolo26n.pt", "yolo26s.pt", "yolo26m.pt"]})
    from vision_model import VisionModel
    custom   = VisionModel.list_local_models("detect")
    defaults = ["yolo26n.pt", "yolo26s.pt", "yolo26m.pt"]
    return JSONResponse({"custom": custom, "defaults": defaults})

@app.post("/api/yolo/config")
async def update_yolo_config(req: YOLOConfigRequest):
    return await update_vision_config({
        "pipeline_mode": "detect" if req.enabled else "off",
        "models": {"detect": req.model}, "imgsz": {"detect": req.imgsz},
        "confidence": {"default": req.confidence}})


# ──────────────────────────────────────────────────────────────
# RC injection routes (Fase 3 — pendiente validación de protocolo,
# ver docs/RC_INJECTION.md)
# ──────────────────────────────────────────────────────────────
@app.get("/api/rc/status")
async def get_rc_status():
    return JSONResponse({**injector.status,
                         "serial_connected": system_status["connected"]})

@app.post("/api/rc/config")
async def update_rc_config(req: RCConfigRequest):
    if req.enabled and not system_status["connected"]:
        return JSONResponse({"error": "Serial no conectado — la inyección requiere la TX12 por USB"},
                            status_code=409)
    try:
        sync = int(req.sync_byte, 16)
    except ValueError:
        return JSONResponse({"error": f"sync_byte inválido: {req.sync_byte}"}, status_code=400)
    if sync not in (0xEE, 0xEA, 0xC8):
        return JSONResponse({"error": "sync_byte debe ser 0xEE, 0xEA o 0xC8"}, status_code=400)
    injector.rate_hz    = max(1.0, min(250.0, req.rate_hz))
    injector.deadman_ms = max(100.0, min(5000.0, req.deadman_ms))
    injector.sync_byte  = sync
    if not req.enabled:
        injector.reset()
        injector.send_failsafe()
    if req.enabled and not injector.enabled:
        injector.reset()   # arranca en failsafe hasta el primer comando
    injector.enabled = req.enabled
    log.info("RC configurado enabled=%s rate_hz=%s deadman_ms=%s sync=0x%02X",
             injector.enabled, injector.rate_hz, injector.deadman_ms, injector.sync_byte)
    return JSONResponse({"updated": True, **injector.status})

@app.post("/api/rc/acquire")
async def acquire_rc(req: RCChannelsRequest):
    try:
        return {"epoch": injector.acquire("http", req.channels)}
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@app.post("/api/rc/channels")
async def set_rc_channels(req: RCChannelsRequest):
    try:
        applied = injector.set_channels(req.channels, "http", req.epoch)
    except (ValueError, TypeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"updated": True, "applied": applied,
                         "failsafe_active": injector.failsafe_active})

@app.post("/api/rc/center")
async def center_rc_channels():
    injector.center()
    injector.send_failsafe()
    return JSONResponse({"centered": True, "channels_us": injector.status["channels_us"]})

@app.websocket("/ws/rc")
async def rc_websocket(ws: WebSocket):
    """Canal de baja latencia para el panel de control manual / gamepad.
    Adquirir: {"action": "acquire", "channels": {16 canales}}.
    Comandos: {"epoch": token, "channels": {16 canales}}.
    Desconectar revoca inmediatamente al propietario y envía failsafe."""
    await ws.accept()
    log.info("WebSocket RC conectado")
    owner = object()
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
                if not isinstance(data, dict):
                    raise ValueError("Mensaje RC inválido")
                if data.get("action") == "acquire":
                    epoch = injector.acquire(owner, data.get("channels"))
                    await ws.send_text(json.dumps({"ok": True, "epoch": epoch}))
                    continue
                applied = injector.set_channels(data.get("channels"), owner, data.get("epoch"))
                await ws.send_text(json.dumps({
                    "ok": True, "applied": {str(k): v for k, v in applied.items()},
                    "failsafe_active": injector.failsafe_active,
                    "enabled": injector.enabled}))
            except (ValueError, TypeError, KeyError) as e:
                await ws.send_text(json.dumps({"ok": False, "error": str(e)}))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("WebSocket RC terminó inesperadamente")
    finally:
        injector.release(owner)
        log.info("WebSocket RC desconectado; propietario revocado")


@app.post("/offer")
async def webrtc_offer(request: FRequest):
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Video no disponible"}, status_code=503)
    if not video.capture.is_running:
        return JSONResponse({"error": "Captura no iniciada. Llama /api/video/start primero"}, status_code=400)
    body     = await request.json()
    sdp      = body.get("sdp")
    sdp_type = body.get("type", "offer")
    peer_id  = body.get("peer_id", f"peer_{int(time.time()*1000)}")
    if not sdp:
        return JSONResponse({"error": "SDP requerido"}, status_code=400)
    answer = await video.handle_offer(sdp, sdp_type, peer_id)
    if not answer:
        return JSONResponse({"error": "No se pudo crear answer"}, status_code=500)
    log.info("WebRTC offer aceptada peer_id=%s", peer_id)
    return JSONResponse(answer)


# ──────────────────────────────────────────────────────────────
# Frontend serving — el catch-all DEBE ser el último GET registrado
# ──────────────────────────────────────────────────────────────
frontend_path = Path(__file__).resolve().parent.parent / "frontend"

if frontend_path.exists():
    @app.get("/css/{file_path:path}")
    async def serve_css(file_path: str):
        f = frontend_path / "css" / file_path
        return FileResponse(f, media_type="text/css", headers={"Cache-Control": "no-cache"}) if f.exists() else JSONResponse({}, 404)

    @app.get("/js/{file_path:path}")
    async def serve_js(file_path: str):
        f = frontend_path / "js" / file_path
        return FileResponse(f, media_type="application/javascript", headers={"Cache-Control": "no-cache"}) if f.exists() else JSONResponse({}, 404)

    @app.get("/logs.html")
    async def serve_logs_page():
        f = frontend_path / "logs.html"
        return FileResponse(f) if f.exists() else JSONResponse({"error": "logs.html not found"}, 404)

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/") or full_path == "ws":
            return JSONResponse({"error": "Not found"}, status_code=404)
        index = frontend_path / "index.html"
        return FileResponse(index, headers={"Cache-Control": "no-cache"}) if index.exists() else JSONResponse({"error": "Not found"}, 404)
else:
    @app.get("/")
    async def root(): return JSONResponse({"message": "ELRS v2.7.1", "error": "frontend/ not found"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ELRS Telemetry Server v2.7.1")
    parser.add_argument("--port", default=None, help="Puerto inicial opcional; seleccionable desde la interfaz")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--app-log-level", choices=list(LEVELS), default=APP_LOG_CONFIG.level)
    parser.add_argument("--app-log-dir", default=str(APP_LOG_CONFIG.directory))
    parser.add_argument("--app-log-max-bytes", type=int, default=APP_LOG_CONFIG.max_bytes)
    parser.add_argument("--app-log-backups", type=int, default=APP_LOG_CONFIG.backups)
    parser.add_argument("--app-log-keep-runs", type=int, default=APP_LOG_CONFIG.keep_runs)
    args = parser.parse_args()
    log.info("ELRS Telemetry Server v2.7.1 port=%s baud=%s url=http://localhost:%s",
             args.port, args.baud, args.web_port)
    uvicorn.run(app, host=args.host, port=args.web_port, log_level="warning", log_config=None)
