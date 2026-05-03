"""
ELRS Backend WebSocket Server v2.0
"""
import asyncio, json, argparse
from datetime import datetime, timezone
from pathlib import Path
from collections import deque
from typing import Optional, List
import struct

import serial
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
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
