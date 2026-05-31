"""
ELRS Backend WebSocket Server v2.0
"""
import asyncio, json, argparse
from datetime import datetime, timezone
from pathlib import Path
from collections import deque
from typing import Optional, List
import struct
import time

import serial
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request as FRequest
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from session_manager import SessionManager

CRSF_SYNC = 0xEA

def crc8_dvb_s2(data: bytes) -> int:
    crc_table = [0]*256
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c<<1)^0xD5)&0xFF if (c&0x80) else (c<<1)&0xFF
        crc_table[i] = c
    crc = 0
    for b in data:
        crc = crc_table[crc ^ b]
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
        print(f"[WS] Conectado. Total: {len(self.active_connections)}")
    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections: self.active_connections.remove(ws)
    async def broadcast(self, msg: dict):
        if not self.active_connections: return
        j = json.dumps(msg)
        await asyncio.gather(*[self._send(c, j) for c in self.active_connections], return_exceptions=True)
    async def _send(self, ws: WebSocket, msg: str):
        try: await ws.send_text(msg)
        except:
            if ws in self.active_connections: self.active_connections.remove(ws)

app = FastAPI(title="ELRS Telemetry Server", version="2.0.0")
manager = ConnectionManager()
session: Optional[SessionManager] = None
telemetry_history = deque(maxlen=500)
system_status = {"serial_port": None, "baud_rate": None, "connected": False,
                 "frames_received": 0, "uptime_seconds": 0, "start_time": None,
                 "current_session_id": None, "current_session_frames": 0}

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ──────────────────────────────────────────────────────────────
# VIDEO — Import (antes de las rutas para evitar que el catch-all
#         de frontend bloquee GET /api/video/*)
# ──────────────────────────────────────────────────────────────
try:
    from video_streamer import VideoStreamer, CONFIG_FILE, load_video_config
    video = VideoStreamer()
    VIDEO_AVAILABLE = True
    print("[VIDEO] Módulo de video cargado correctamente")
except ImportError as e:
    VIDEO_AVAILABLE = False
    video = None
    CONFIG_FILE = None
    load_video_config = None
    print(f"[VIDEO] Módulo no disponible: {e}")
    print("[VIDEO] Instala dependencias: pip install aiortc opencv-python")


# ──────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────
class VideoStartRequest(BaseModel):
    device_id: int   = 0
    width:     int   = 1280
    height:    int   = 720
    fps:       int   = 30

class VideoConfigRequest(BaseModel):
    brightness: int   = 0
    contrast:   int   = 32
    saturation: int   = 60
    gamma:      float = 1.0
    hist_eq:    bool  = False
    wb_r:       float = 1.0
    wb_g:       float = 1.0
    wb_b:       float = 1.0

class YOLOConfigRequest(BaseModel):
    enabled:    bool  = False
    model:      str   = "yolov8n.pt"
    confidence: float = 0.5


# ──────────────────────────────────────────────────────────────
# Serial reader
# ──────────────────────────────────────────────────────────────
async def serial_reader_task(port: str, baud: int):
    global session
    try:
        ser = serial.Serial(port, baud, timeout=0.001)
        system_status.update({"connected": True, "serial_port": port, "baud_rate": baud})
        print(f"[SERIAL] Conectado a {port} @ {baud} baud")
    except Exception as e:
        print(f"[SERIAL] Error: {e}"); system_status["connected"] = False; return
    buf = bytearray()
    while True:
        try:
            data = ser.read(256)
            if data: buf.extend(data)
            while len(buf) >= 4:
                if buf[0] != CRSF_SYNC: buf.pop(0); continue
                total_len = buf[1] + 2
                if len(buf) < total_len: break
                frame = bytes(buf[:total_len]); buf = buf[total_len:]
                parsed = parse_crsf_frame(frame)
                if parsed:
                    ts = datetime.now(timezone.utc).isoformat()
                    fd = {"timestamp": ts, **parsed}
                    telemetry_history.append(fd)
                    system_status["frames_received"] += 1
                    if session:
                        session.record(parsed["type"], parsed["data"], ts)
                        system_status["current_session_frames"] = session.current_frame_count
                    await manager.broadcast(fd)
            if not data: await asyncio.sleep(0)
        except Exception as e:
            print(f"[SERIAL] Error: {e}"); await asyncio.sleep(0.1)


# ──────────────────────────────────────────────────────────────
# Telemetry routes
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: manager.disconnect(ws)

@app.get("/api/status")
async def get_status():
    if system_status["start_time"]:
        system_status["uptime_seconds"] = int((datetime.now(timezone.utc) - system_status["start_time"]).total_seconds())
    return JSONResponse(system_status)

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
    sessions = SessionManager.list_sessions()
    current = None
    if session and session.current_frame_count > 0:
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
    if not session or session.current_frame_count == 0:
        return JSONResponse({"error": "Sin datos"}, status_code=400)
    path = session.save(); saved_id = session.session_id
    session = SessionManager()
    system_status["current_session_id"] = session.session_id
    system_status["current_session_frames"] = 0
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
async def get_video_config():
    if not VIDEO_AVAILABLE or not load_video_config:
        return JSONResponse({"brightness": 0, "contrast": 32, "saturation": 60,
                             "gamma": 1.0, "hist_eq": False,
                             "wb_r": 1.0, "wb_g": 1.0, "wb_b": 1.0})
    return JSONResponse(load_video_config())

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
    if CONFIG_FILE and load_video_config:
        existing = load_video_config()
        existing.update(cfg)
        with open(CONFIG_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    if video.capture.is_running:
        video.capture.update_config(cfg)
    return JSONResponse({"updated": True, "config": cfg})

@app.post("/api/video/start")
async def start_video(req: VideoStartRequest):
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Módulo de video no disponible"}, status_code=503)
    ok = await video.start_capture(req.device_id, req.width, req.height, req.fps)
    if not ok:
        return JSONResponse({"error": f"No se pudo abrir dispositivo {req.device_id}"}, status_code=500)
    return JSONResponse({"started": True, "device_id": req.device_id,
                         "width": req.width, "height": req.height, "fps": req.fps})

@app.post("/api/video/stop")
async def stop_video():
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Módulo de video no disponible"}, status_code=503)
    await video.stop_capture()
    return JSONResponse({"stopped": True})

@app.post("/api/video/recording/start")
async def start_recording():
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Módulo de video no disponible"}, status_code=503)
    if not video.capture.is_running:
        return JSONResponse({"error": "Captura no iniciada"}, status_code=400)
    sid = session.session_id if session else datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = video.start_recording(sid)
    return JSONResponse({"recording": True, "session_id": sid, "path": path})

@app.post("/api/video/recording/stop")
async def stop_recording():
    if not VIDEO_AVAILABLE or not video:
        return JSONResponse({"error": "Módulo de video no disponible"}, status_code=503)
    path = video.stop_recording()
    return JSONResponse({"recording": False, "saved": path})

# ──────────────────────────────────────────────────────────────
# YOLO routes
# ──────────────────────────────────────────────────────────────
@app.get("/api/yolo/status")
async def get_yolo_status():
    if not VIDEO_AVAILABLE or not video or not video.yolo:
        return JSONResponse({"available": False})
    return JSONResponse(video.yolo.status)

@app.get("/api/yolo/models")
async def list_yolo_models():
    if not VIDEO_AVAILABLE or not video or not video.yolo:
        return JSONResponse({"custom": [], "defaults": ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt"]})
    from yolo_processor import YOLOProcessor
    custom   = YOLOProcessor.list_local_models()
    defaults = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt"]
    return JSONResponse({"custom": custom, "defaults": defaults})

@app.post("/api/yolo/config")
async def update_yolo_config(req: YOLOConfigRequest):
    if not VIDEO_AVAILABLE or not video or not video.yolo:
        return JSONResponse({"error": "YOLO no disponible"}, status_code=503)
    yolo = video.yolo
    if not yolo.is_available():
        return JSONResponse({"error": "ultralytics no instalado — pip install ultralytics"}, status_code=503)
    # Cargar modelo si cambió o no hay ninguno cargado
    if req.enabled and (req.model != yolo._model_path or yolo._model is None):
        loop = asyncio.get_event_loop()
        ok   = await loop.run_in_executor(None, yolo.load_model, req.model)
        if not ok:
            return JSONResponse({"error": f"No se pudo cargar {req.model}"}, status_code=500)
    yolo.enabled    = req.enabled
    yolo.confidence = req.confidence
    return JSONResponse({"updated": True, **yolo.status})


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
    return JSONResponse(answer)


# ──────────────────────────────────────────────────────────────
# Frontend serving — el catch-all DEBE ser el último GET registrado
# ──────────────────────────────────────────────────────────────
frontend_path = Path(__file__).parent / "frontend-vanilla"

if frontend_path.exists():
    @app.get("/css/{file_path:path}")
    async def serve_css(file_path: str):
        f = frontend_path / "css" / file_path
        return FileResponse(f, media_type="text/css") if f.exists() else JSONResponse({}, 404)

    @app.get("/js/{file_path:path}")
    async def serve_js(file_path: str):
        f = frontend_path / "js" / file_path
        return FileResponse(f, media_type="application/javascript") if f.exists() else JSONResponse({}, 404)

    @app.get("/logs.html")
    async def serve_logs_page():
        f = frontend_path / "logs.html"
        return FileResponse(f) if f.exists() else JSONResponse({"error": "logs.html not found"}, 404)

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/") or full_path == "ws":
            return JSONResponse({"error": "Not found"}, status_code=404)
        index = frontend_path / "index.html"
        return FileResponse(index) if index.exists() else JSONResponse({"error": "Not found"}, 404)
else:
    @app.get("/")
    async def root(): return JSONResponse({"message": "ELRS v2.0", "error": "frontend-vanilla/ not found"})


# ──────────────────────────────────────────────────────────────
# Startup / Shutdown
# ──────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    global session
    system_status["start_time"] = datetime.now(timezone.utc)
    session = SessionManager()
    system_status["current_session_id"] = session.session_id
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM6")
    parser.add_argument("--baud", type=int, default=115200)
    args, _ = parser.parse_known_args()
    asyncio.create_task(serial_reader_task(args.port, args.baud))
    print("[SERVER] ELRS Telemetry Server v2.0 listo")

@app.on_event("shutdown")
async def shutdown_event():
    if session and session.current_frame_count > 0:
        print("[SERVER] Guardando sesión..."); session.save()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ELRS Telemetry Server v2.0")
    parser.add_argument("--port", default="COM6")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--web-port", type=int, default=8080)
    args = parser.parse_args()
    print(f"ELRS Telemetry Server v2.0 | {args.port}@{args.baud} | http://localhost:{args.web_port}")
    uvicorn.run(app, host=args.host, port=args.web_port, log_level="warning")
