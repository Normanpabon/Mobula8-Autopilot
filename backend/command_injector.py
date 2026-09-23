"""
CommandInjector — Inyección de comandos RC hacia la TX12 (Fase 3)
=================================================================
Construye frames CRSF RC Channels Packed (tipo 0x16, 16 canales × 11 bits)
y los envía por el mismo puerto serial USB donde la TX12 refleja la
telemetría. Diseño (ver docs/RC_INJECTION.md):

- **Loop de envío a ritmo fijo** (default 50 Hz): CRSF espera un stream
  continuo de frames RC, no comandos sueltos. El estado de canales se
  actualiza via API/WS y el loop envía siempre el último estado.
- **Deadman switch**: si no llega ninguna actualización de canales en
  `deadman_ms` (default 500 ms), el loop envía los valores de failsafe
  (throttle al mínimo, roll/pitch/yaw centrados, aux abajo) hasta recibir
  una adquisición explícita con estado completo y throttle mínimo. También aplica antes del primer comando.
- **Sin serial, sin inyección**: recibe un `write_fn` (callable → bool);
  si el puerto no está conectado la inyección no se puede habilitar.

⚠ PENDIENTE DE VALIDACIÓN DE PROTOCOLO (roadmap): no está confirmado que
EdgeTX acepte CRSF de entrada por USB serial en modo Telem Mirror. Este
módulo implementa el lado PC completo; USB Joystick exporta canales hacia el PC y no es una ruta de entrada.
La interfaz PC → EdgeTX requiere validación física independiente.
El byte de dirección es configurable (`sync_byte`) para poder probar
0xEE (módulo transmisor), 0xEA (radio) o 0xC8 (FC) en la validación.

Convención de canales (Betaflight AETR): 1=roll, 2=pitch, 3=throttle,
4=yaw, 5–16=aux. Valores en microsegundos 988–2012 (1500 = centro).
"""

import asyncio
import time
import logging
import math
import uuid
from typing import Callable, Optional

log = logging.getLogger("command_injector")

FRAME_TYPE_RC = 0x16

# Direcciones CRSF candidatas para la validación de protocolo
ADDR_TRANSMITTER = 0xEE   # módulo transmisor (default)
ADDR_RADIO       = 0xEA   # radio (el que usa Telem Mirror hacia el PC)
ADDR_FC          = 0xC8   # flight controller

# Mapeo µs ↔ ticks CRSF: 988 µs = 172, 1500 µs = 992, 2012 µs = 1811
TICKS_MIN, TICKS_MID, TICKS_MAX = 172, 992, 1811
US_MIN, US_MID, US_MAX = 988.0, 1500.0, 2012.0

# Tabla CRC8 DVB-S2 (idéntica a la del parser en elrs_backend.py;
# duplicada aquí para que el módulo sea standalone/testeable)
_CRC_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = ((_c << 1) ^ 0xD5) & 0xFF if (_c & 0x80) else (_c << 1) & 0xFF
    _CRC_TABLE.append(_c)


def crc8_dvb_s2(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = _CRC_TABLE[crc ^ b]
    return crc


def us_to_ticks(us: float) -> int:
    """Microsegundos (988–2012) → ticks CRSF (172–1811)."""
    ticks = round(TICKS_MID + (us - US_MID) * 8 / 5)
    return max(TICKS_MIN, min(TICKS_MAX, ticks))


def ticks_to_us(ticks: int) -> float:
    """Ticks CRSF → microsegundos (para tests/telemetría de estado)."""
    return round(US_MID + (ticks - TICKS_MID) * 5 / 8, 1)


# Nombres AETR → índice de canal 1-based
CHANNEL_ALIASES = {"roll": 1, "pitch": 2, "throttle": 3, "yaw": 4}


class CommandInjector:
    """
    Estado de los 16 canales + loop de envío + deadman.
    `write_fn(frame: bytes) -> bool` escribe al serial; None = sin puerto.
    """

    CHANNELS = 16

    def __init__(self, write_fn: Optional[Callable[[bytes], bool]] = None):
        self._write     = write_fn
        self.enabled    = False
        self.rate_hz    = 50.0
        self.deadman_ms = 500.0
        self.sync_byte  = ADDR_TRANSMITTER

        # AETR: throttle (ch3) al mínimo, el resto centrado, aux abajo
        self.failsafe_us = [US_MID, US_MID, US_MIN, US_MID] + [US_MIN] * 12
        self._channels_us = list(self.failsafe_us)

        self.owner = None
        self.epoch = None
        self._last_cmd_ts = 0.0   # 0 = nunca se recibió un comando
        self._task: Optional[asyncio.Task] = None
        self._running     = False
        self.frames_sent  = 0
        self.write_errors = 0

    @property
    def failsafe_active(self) -> bool:
        """Deadman: sin comandos aún, o el último es más viejo que deadman_ms."""
        return (self._last_cmd_ts == 0.0
                or (time.monotonic() - self._last_cmd_ts) * 1000.0 > self.deadman_ms)

    # ── Canales ──────────────────────────────────────────────────────────────

    def _parse_channels(self, channels):
        if not isinstance(channels, dict) or not channels:
            raise ValueError("Se requiere un estado de canales")
        applied = {}
        for key, us in channels.items():
            idx = CHANNEL_ALIASES.get(str(key).lower())
            if idx is None:
                idx = int(key)
            if not 1 <= idx <= self.CHANNELS or idx in applied:
                raise ValueError("Canal inválido o duplicado")
            value = float(us)
            if not math.isfinite(value) or not US_MIN <= value <= US_MAX:
                raise ValueError("Canal fuera de rango 988–2012")
            applied[idx] = value
        return applied

    def acquire(self, owner, channels):
        if not self.enabled:
            raise ValueError("Habilita RC antes de adquirir control")
        if self.failsafe_active:
            self.reset()
        if self.owner is not None:
            raise ValueError("El control ya tiene propietario")
        applied = self._parse_channels(channels)
        if len(applied) != self.CHANNELS or applied[3] != US_MIN:
            raise ValueError("Adquirir requiere los 16 canales y throttle mínimo")
        self.owner, self.epoch = owner, uuid.uuid4().hex
        self._channels_us = [applied[i] for i in range(1, 17)]
        self._last_cmd_ts = time.monotonic()
        log.info("[RC] Control adquirido owner=%s", "http" if owner == "http" else "websocket")
        return self.epoch

    def set_channels(self, channels, owner=None, epoch=None):
        if self.failsafe_active:
            self.reset()
        if not self.enabled or self.owner is None or owner != self.owner or epoch != self.epoch:
            raise ValueError("Control no adquirido o época expirada; readquiere con throttle mínimo")
        applied = self._parse_channels(channels)
        if len(applied) != self.CHANNELS:
            raise ValueError("Cada comando requiere los 16 canales")
        self._channels_us = [applied[i] for i in range(1, 17)]
        self._last_cmd_ts = time.monotonic()
        log.debug("[RC] Comando aplicado channels_us=%s", self._channels_us)
        return applied

    def center(self):
        self.reset()

    def reset(self):
        was_owned = self.owner is not None
        self._channels_us = list(self.failsafe_us)
        self._last_cmd_ts = 0.0
        self.owner = self.epoch = None
        if was_owned:
            log.warning("[RC] Control revocado; canales en failsafe")

    def release(self, owner):
        if self.owner == owner:
            self.reset()
            self.send_failsafe()

    def send_failsafe(self):
        if self.enabled and self.can_transmit:
            try:
                if self._write(self.build_rc_frame(self.failsafe_us)):
                    self.frames_sent += 1
                else:
                    self.write_errors += 1
            except Exception:
                self.write_errors += 1

    # ── Construcción de frames CRSF ──────────────────────────────────────────

    def build_rc_frame(self, channels_us: Optional[list] = None) -> bytes:
        """
        Frame CRSF RC Channels Packed:
        [sync, len, 0x16, payload 22 bytes (16 canales × 11 bits LE), crc8]
        """
        us = channels_us if channels_us is not None else self._channels_us
        bits = nbits = 0
        payload = bytearray()
        for u in us[:self.CHANNELS]:
            bits |= (us_to_ticks(u) & 0x7FF) << nbits
            nbits += 11
            while nbits >= 8:
                payload.append(bits & 0xFF)
                bits >>= 8
                nbits -= 8
        body = bytes([FRAME_TYPE_RC]) + bytes(payload)
        return bytes([self.sync_byte, len(body) + 1]) + body + bytes([crc8_dvb_s2(body)])

    @staticmethod
    def unpack_rc_frame(frame: bytes) -> list:
        """Decodifica un frame RC a µs (para tests round-trip)."""
        payload = frame[3:-1]
        bits = nbits = 0
        ticks = []
        for b in payload:
            bits |= b << nbits
            nbits += 8
            while nbits >= 11 and len(ticks) < CommandInjector.CHANNELS:
                ticks.append(bits & 0x7FF)
                bits >>= 11
                nbits -= 11
        return [ticks_to_us(t) for t in ticks]

    # ── Loop de envío ────────────────────────────────────────────────────────

    @property
    def can_transmit(self) -> bool:
        return self._write is not None

    def start(self) -> None:
        """Arranca el loop (solo envía cuando enabled=True)."""
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._send_loop())
            log.info("[RC] Loop de envío iniciado")

    async def stop(self) -> None:
        self._running = False
        self.reset()
        self.send_failsafe()
        self.enabled  = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("[RC] Loop de envío detenido")

    async def _send_loop(self):
        while self._running:
            period = 1.0 / max(self.rate_hz, 1.0)
            if not (self.enabled and self.can_transmit):
                await asyncio.sleep(0.1)
                continue

            # Deadman: sin comandos recientes (o nunca) → valores de failsafe
            if self.failsafe_active:
                self.reset()
            us = self._channels_us

            try:
                if self._write(self.build_rc_frame(us)):
                    self.frames_sent += 1
                else:
                    self.write_errors += 1
            except Exception as e:
                self.write_errors += 1
                log.exception("[RC] Error escribiendo frame: %s", e)
                await asyncio.sleep(0.5)
            await asyncio.sleep(period)

    # ── Estado ───────────────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        age_ms = ((time.monotonic() - self._last_cmd_ts) * 1000.0
                  if self._last_cmd_ts else None)
        return {
            "control_owned":    self.owner is not None and not self.failsafe_active,
            "available":        self.can_transmit,
            "enabled":          self.enabled,
            "running":          self._running,
            "rate_hz":          self.rate_hz,
            "deadman_ms":       self.deadman_ms,
            "sync_byte":        f"0x{self.sync_byte:02X}",
            "failsafe_active":  self.failsafe_active,
            "last_command_age_ms": round(age_ms, 1) if age_ms is not None else None,
            "frames_sent":      self.frames_sent,
            "write_errors":     self.write_errors,
            "channels_us":      [round(u, 1) for u in self._channels_us],
            "failsafe_us":      [round(u, 1) for u in self.failsafe_us],
        }
