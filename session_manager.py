"""
session_manager.py — Gestión de sesiones de vuelo
===================================================
Guarda automáticamente cada sesión de vuelo en formato JSON.
Usado por elrs_backend.py — no ejecutar directamente.

Estructura de un archivo de sesión:
    logs/session_YYYYMMDD_HHMMSS.json
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class SessionManager:
    """
    Gestiona una sesión de vuelo activa: acumula frames de telemetría
    y los guarda en disco al finalizar.
    """

    def __init__(self):
        self.session_id   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.start_time   = datetime.now(timezone.utc)
        self._frames: list = []
        print(f"[SESSION] Nueva sesión: {self.session_id}")
        print(f"[SESSION] Logs en: {LOGS_DIR.resolve()}")

    # ── Propiedades de estado ────────────────────────────────────

    @property
    def current_frame_count(self) -> int:
        return len(self._frames)

    @property
    def current_duration(self) -> float:
        """Duración en segundos desde el inicio de la sesión."""
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    # ── Grabación de frames ──────────────────────────────────────

    def record(self, frame_type: str, data: dict, timestamp: Optional[str] = None) -> None:
        """
        Registra un frame de telemetría.

        Args:
            frame_type: "link" | "battery" | "attitude" | "flight_mode"
            data:       Diccionario con los valores del frame
            timestamp:  ISO 8601 UTC (si None, se genera ahora)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        self._frames.append({
            "timestamp": timestamp,
            "type":      frame_type,
            "data":      data,
        })

    # ── Guardar sesión ───────────────────────────────────────────

    def save(self) -> str:
        """
        Guarda la sesión en disco y retorna el path del archivo.
        """
        end_time = datetime.now(timezone.utc)
        summary  = self._build_summary(end_time)

        doc = {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "end_time":   end_time.isoformat(),
            "summary":    summary,
            "frames":     self._frames,
        }

        path = LOGS_DIR / f"session_{self.session_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)

        size_kb = path.stat().st_size / 1024
        print(
            f"[SESSION] Sesión guardada: {path.name} "
            f"({self.current_frame_count} frames, "
            f"{summary['duration_seconds']:.1f}s, "
            f"{size_kb:.1f} KB)"
        )
        return str(path)

    # ── Resumen ──────────────────────────────────────────────────

    def _build_summary(self, end_time: datetime) -> dict:
        """Calcula métricas agregadas de todos los frames grabados."""
        duration = (end_time - self.start_time).total_seconds()

        bat_frames  = [f for f in self._frames if f["type"] == "battery"]
        link_frames = [f for f in self._frames if f["type"] == "link"]
        att_frames  = [f for f in self._frames if f["type"] == "attitude"]
        fm_frames   = [f for f in self._frames if f["type"] == "flight_mode"]

        # ── Batería ──
        voltages  = [f["data"].get("voltage", 0)  for f in bat_frames]
        currents  = [f["data"].get("current", 0)  for f in bat_frames]
        mahs      = [f["data"].get("mah_used", 0) for f in bat_frames]
        percents  = [f["data"].get("percent", 100) for f in bat_frames]

        max_voltage  = max(voltages,  default=0.0)
        min_voltage  = min(voltages,  default=0.0)
        avg_voltage  = (sum(voltages) / len(voltages)) if voltages else 0.0
        max_current  = max(currents,  default=0.0)
        total_mah    = max(mahs,      default=0)
        min_bat_pct  = min(percents,  default=0)

        # ── Link ──
        rssi_vals = [f["data"].get("rssi1", -120) for f in link_frames]
        lq_vals   = [f["data"].get("lq",       0) for f in link_frames]

        avg_rssi = (sum(rssi_vals) / len(rssi_vals)) if rssi_vals else -120.0
        min_rssi = min(rssi_vals, default=-120.0)
        avg_lq   = (sum(lq_vals)  / len(lq_vals))   if lq_vals   else 0.0
        min_lq   = min(lq_vals,   default=0)

        # ── Actitud ──
        pitches = [abs(f["data"].get("pitch", 0)) for f in att_frames]
        rolls   = [abs(f["data"].get("roll",  0)) for f in att_frames]
        max_pitch = max(pitches, default=0.0)
        max_roll  = max(rolls,   default=0.0)

        # ── Modos de vuelo ──
        flight_modes = list({
            f["data"].get("mode", "").strip()
            for f in fm_frames
            if f["data"].get("mode", "").strip()
        })

        # ── Conteo por tipo ──
        frame_counts = {
            "link":        len(link_frames),
            "battery":     len(bat_frames),
            "attitude":    len(att_frames),
            "flight_mode": len(fm_frames),
        }

        return {
            "total_frames":     len(self._frames),
            "duration_seconds": round(duration, 1),
            "max_voltage":      round(max_voltage,  2),
            "min_voltage":      round(min_voltage,  2),
            "avg_voltage":      round(avg_voltage,  2),
            "max_current":      round(max_current,  2),
            "total_mah":        round(total_mah,    1),
            "min_battery_pct":  min_bat_pct,
            "avg_rssi":         round(avg_rssi,     1),
            "min_rssi":         round(min_rssi,     1),
            "avg_lq":           round(avg_lq,       1),
            "min_lq":           min_lq,
            "max_pitch":        round(max_pitch,    2),
            "max_roll":         round(max_roll,     2),
            "flight_modes":     flight_modes,
            "frame_counts":     frame_counts,
        }

    # ── Métodos estáticos (operaciones sobre sesiones guardadas) ─

    @staticmethod
    def list_sessions() -> list:
        """
        Retorna la lista de sesiones guardadas, ordenadas de más
        reciente a más antigua, con metadatos básicos.
        """
        sessions = []
        for path in sorted(LOGS_DIR.glob("session_*.json"), reverse=True):
            try:
                with open(path, encoding="utf-8") as f:
                    doc = json.load(f)
                sessions.append({
                    "session_id": doc.get("session_id"),
                    "start_time": doc.get("start_time"),
                    "end_time":   doc.get("end_time"),
                    "summary":    doc.get("summary", {}),
                    "size_kb":    round(path.stat().st_size / 1024, 1),
                })
            except Exception as e:
                print(f"[SESSION] Error leyendo {path.name}: {e}")
        return sessions

    @staticmethod
    def get_session(session_id: str) -> Optional[dict]:
        """Carga y retorna los datos completos de una sesión."""
        path = LOGS_DIR / f"session_{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[SESSION] Error leyendo sesión {session_id}: {e}")
            return None

    @staticmethod
    def delete_session(session_id: str) -> bool:
        """Elimina una sesión del disco. Retorna True si tuvo éxito."""
        path = LOGS_DIR / f"session_{session_id}.json"
        if not path.exists():
            return False
        try:
            path.unlink()
            print(f"[SESSION] Sesión eliminada: {session_id}")
            return True
        except Exception as e:
            print(f"[SESSION] Error eliminando {session_id}: {e}")
            return False
