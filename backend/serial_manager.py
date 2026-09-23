"""Single owner of serial I/O and cancellable reconnect lifecycle."""
import asyncio
import logging
import time
import serial

log = logging.getLogger("serial_manager")


class SerialManager:
    def __init__(self, status, enumerate_ports, on_data, on_loss):
        self.status = status
        self.enumerate_ports = enumerate_ports
        self.on_data = on_data
        self.on_loss = on_loss
        self.ser = None
        self.task = None
        self.lock = asyncio.Lock()
        self.port = None
        self.baud = None
        self.retry_initial = 0.5
        self.status.update(serial_state='DISCONNECTED', serial_errors=0, serial_reconnects=0)

    def close(self):
        was_open = self.ser is not None
        self.status['connected'] = False
        self.on_loss()
        ser, self.ser = self.ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                log.exception("Error cerrando puerto serial")
        if was_open:
            log.info("Puerto serial cerrado port=%s", self.port)

    def error(self, exc):
        self.status.update(serial_state='ERROR', serial_error=str(exc))
        self.status['serial_errors'] += 1
        log.error("Error serial port=%s baud=%s: %s", self.port, self.baud, exc, exc_info=True)
        self.close()

    def open(self):
        self.status['serial_state'] = 'CONNECTING'
        log.info("Abriendo puerto serial port=%s baud=%s", self.port, self.baud)
        try:
            if self.port not in {p['device'] for p in self.enumerate_ports()}:
                raise OSError(f'Puerto no disponible: {self.port}')
            self.ser = serial.Serial(self.port, self.baud, timeout=0, write_timeout=0.05)
            self.status.update(connected=True, serial_state='CONNECTED', serial_error=None)
            log.info("Puerto abierto port=%s baud=%s; esperando tramas CRSF", self.port, self.baud)
            return True
        except (OSError, ValueError, serial.SerialException) as exc:
            self.error(exc)
            return False

    async def disconnect(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        self.close()
        self.port = None
        self.status.update(serial_state='DISCONNECTED', serial_port=None, baud_rate=None, serial_error=None)
        log.info("Serial desconectado")

    async def connect(self, port, baud):
        await self.disconnect()
        self.port, self.baud = port, baud
        self.status.update(serial_port=port, baud_rate=baud)
        connected = self.open()
        self.task = asyncio.create_task(self.run())
        log.info("Solicitud serial port=%s baud=%s opened=%s", port, baud, connected)
        return connected

    def write(self, frame):
        if self.ser is None:
            return False
        try:
            if self.ser.write(frame) != len(frame):
                raise OSError('Escritura serial incompleta')
            return True
        except (OSError, serial.SerialException) as exc:
            self.error(exc)
            return False

    async def run(self):
        delay = self.retry_initial
        last_report = time.monotonic()
        last_frames = self.status.get('frames_received', 0)
        try:
            while True:
                if self.ser is None:
                    self.status['serial_state'] = 'RETRY_WAIT'
                    log.warning("Reintento serial port=%s en %.1f s", self.port, delay)
                    await asyncio.sleep(delay)
                    if not self.open():
                        delay = min(delay * 2, 10.0)
                        continue
                    self.status['serial_reconnects'] += 1
                    log.info("Serial reconectado port=%s reconnects=%s", self.port, self.status['serial_reconnects'])
                try:
                    data = self.ser.read(256)
                    if data:
                        delay = self.retry_initial
                        await self.on_data(data)
                except (OSError, serial.SerialException) as exc:
                    self.error(exc)
                now = time.monotonic()
                if now - last_report >= 10:
                    log.debug("Serial health port=%s state=%s bytes=%s valid=%s telemetry=%s by_type=%s crc_errors=%s unknown=%s unknown_types=%s sync_discarded=%s discarded_heads=%s",
                              self.port, self.status['serial_state'], self.status.get('serial_bytes_received', 0),
                              self.status.get('serial_valid_frames', 0), self.status.get('frames_received', 0),
                              self.status.get('frames_by_type', {}), self.status.get('serial_crc_errors', 0),
                              self.status.get('serial_unknown_frames', 0), self.status.get('serial_unknown_types', {}),
                              self.status.get('serial_sync_discarded', 0), self.status.get('serial_discarded_heads', {}))
                    frames = self.status.get('frames_received', 0)
                    if self.ser is not None and frames == last_frames:
                        log.warning("Puerto abierto sin nuevas muestras de telemetría port=%s bytes=%s valid=%s",
                                    self.port, self.status.get('serial_bytes_received', 0),
                                    self.status.get('serial_valid_frames', 0))
                    last_frames = frames
                    last_report = now
                await asyncio.sleep(0.005)
        finally:
            self.close()
