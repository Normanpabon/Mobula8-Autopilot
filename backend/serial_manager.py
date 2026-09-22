"""Single owner of serial I/O and cancellable reconnect lifecycle."""
import asyncio
import serial


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
        self.status['connected'] = False
        self.on_loss()
        ser, self.ser = self.ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def error(self, exc):
        self.status.update(serial_state='ERROR', serial_error=str(exc))
        self.status['serial_errors'] += 1
        self.close()

    def open(self):
        self.status['serial_state'] = 'CONNECTING'
        try:
            if self.port not in {p['device'] for p in self.enumerate_ports()}:
                raise OSError(f'Puerto no disponible: {self.port}')
            self.ser = serial.Serial(self.port, self.baud, timeout=0, write_timeout=0.05)
            self.status.update(connected=True, serial_state='CONNECTED', serial_error=None)
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

    async def connect(self, port, baud):
        await self.disconnect()
        self.port, self.baud = port, baud
        self.status.update(serial_port=port, baud_rate=baud)
        connected = self.open()
        self.task = asyncio.create_task(self.run())
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
        try:
            while True:
                if self.ser is None:
                    self.status['serial_state'] = 'RETRY_WAIT'
                    await asyncio.sleep(delay)
                    if not self.open():
                        delay = min(delay * 2, 10.0)
                        continue
                    self.status['serial_reconnects'] += 1
                try:
                    data = self.ser.read(256)
                    if data:
                        delay = self.retry_initial
                        await self.on_data(data)
                except (OSError, serial.SerialException) as exc:
                    self.error(exc)
                await asyncio.sleep(0.005)
        finally:
            self.close()
