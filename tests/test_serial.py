"""Serial lifecycle/API regressions, without a physical controller."""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import httpx
import serial
import elrs_backend as api


class Device:
    def __init__(self, *args, **kwargs):
        self.is_open = True
        self.fail = False

    def read(self, size):
        if self.fail:
            raise serial.SerialException('USB disconnected')
        return b''

    def close(self):
        self.is_open = False


class SerialTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.devices = []
        def factory(*args, **kwargs):
            device = Device()
            self.devices.append(device)
            return device
        for target, value in [
            ('platform.system', lambda: 'Linux'),
            ('list_ports.comports', lambda: [SimpleNamespace(device=p, description='Radio')
                                           for p in ['/dev/ttyACM0', '/dev/ttyUSB0']]),
            ('serial.Serial', factory),
        ]:
            patcher = patch('elrs_backend.' + target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        api.serial_manager.retry_initial = 0.03
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test')
        self.addAsyncCleanup(self.client.aclose)
        self.addAsyncCleanup(api.disconnect_serial)

    async def connect(self, port='/dev/ttyACM0'):
        return await self.client.post('/api/serial/connect', json={'port': port})

    async def test_switch_closes_previous_resets_rc_and_shutdown(self):
        self.assertEqual((await self.connect()).status_code, 200)
        first_task = api.serial_manager.task
        api.injector.enabled = True
        epoch = api.injector.acquire('test', dict(enumerate(api.injector.failsafe_us, 1)))
        channels = dict(enumerate(api.injector.failsafe_us, 1))
        channels[3] = 1800
        api.injector.set_channels(channels, 'test', epoch)
        self.assertEqual((await self.connect('/dev/ttyUSB0')).status_code, 200)
        self.assertTrue(first_task.done())
        self.assertFalse(self.devices[0].is_open)
        self.assertTrue(self.devices[1].is_open)
        self.assertFalse(api.injector.enabled)
        self.assertTrue(api.injector.failsafe_active)
        await self.client.post('/api/serial/disconnect')
        self.assertFalse(self.devices[1].is_open)
        self.assertIsNone(api.serial_manager.ser)
        self.assertFalse((await self.client.get('/api/status')).json()['connected'])

    async def test_unplug_and_reconnect_without_restart(self):
        await self.connect()
        api.injector.enabled = True
        self.devices[0].fail = True
        await asyncio.sleep(.02)
        state = (await self.client.get('/api/status')).json()
        self.assertFalse(state['connected'])
        self.assertIn('USB disconnected', state['serial_error'])
        self.assertFalse(api.injector.enabled)
        self.assertFalse(self.devices[0].is_open)
        self.assertEqual((await self.connect()).status_code, 200)
        self.assertIsNone(api.system_status['serial_error'])

    async def test_invalid_port_does_not_interrupt_active_connection(self):
        await self.connect()
        for port in ['COM6', '/etc/passwd', '/dev/missing', '/dev/../etc/passwd']:
            self.assertEqual((await self.connect(port)).status_code, 400)
        self.assertTrue(self.devices[0].is_open)
        self.assertEqual(len(self.devices), 1)
        self.assertEqual((await self.client.post('/api/serial/connect', json={'port': '/dev/ttyACM0', 'baud': 0})).status_code, 422)

    async def test_open_error_and_recovery(self):
        await self.connect()
        with patch.object(api.serial, 'Serial', side_effect=serial.SerialException('Permission denied')):
            self.assertEqual((await self.connect('/dev/ttyUSB0')).status_code, 202)
        self.assertFalse(api.system_status['connected'])
        self.assertIsNone(api.serial_manager.ser)
        self.assertEqual((await self.connect()).status_code, 200)

    async def test_windows_enumeration_and_validation(self):
        with patch.object(api.platform, 'system', return_value='Windows'), patch.object(
                api.list_ports, 'comports', return_value=[SimpleNamespace(device='COM12', description='Radio')]):
            data = (await self.client.get('/api/serial/ports')).json()
            self.assertEqual(data['platform'], 'Windows')
            self.assertEqual(data['ports'][0]['device'], 'COM12')
            self.assertEqual((await self.connect('com12')).status_code, 200)
            self.assertEqual((await self.connect('/dev/ttyACM0')).status_code, 400)

    async def test_concurrent_switches_leave_only_one_port_open(self):
        results = await asyncio.gather(self.connect(), self.connect('/dev/ttyUSB0'))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertEqual(sum(d.is_open for d in self.devices), 1)

    async def test_automatic_reconnect_keeps_rc_disabled(self):
        await self.connect()
        api.injector.enabled = True
        self.devices[0].fail = True
        await asyncio.sleep(.1)
        self.assertTrue(api.system_status['connected'])
        self.assertGreaterEqual(len(self.devices), 2)
        self.assertFalse(api.injector.enabled)
        self.assertIsNone(api.injector.epoch)

    async def test_write_failure_closes_and_retries(self):
        await self.connect()
        self.devices[0].write = lambda frame: 1
        self.assertFalse(api.serial_manager.write(b'frame'))
        self.assertIsNone(api.serial_manager.ser)
        await asyncio.sleep(.1)
        self.assertTrue(api.system_status['connected'])

    async def test_disconnect_cancels_retry(self):
        with patch.object(api.serial, 'Serial', side_effect=serial.SerialException('busy')):
            self.assertEqual((await self.connect()).status_code, 202)
            await api.disconnect_serial()
        await asyncio.sleep(.1)
        self.assertIsNone(api.serial_manager.task)
        self.assertFalse(api.system_status['connected'])

    async def test_linux_stable_alias_survives_renumbering(self):
        class Alias:
            def resolve(self):
                return Path(current[0])
            def __str__(self):
                return '/dev/serial/by-id/usb-radio'
        current = ['/dev/ttyACM0']
        with patch.object(api.Path, 'glob', return_value=[Alias()]), patch.object(
                api.list_ports, 'comports', side_effect=lambda: [SimpleNamespace(device=current[0], description='Radio')]):
            await self.connect()
            self.assertEqual(api.system_status['serial_port'], '/dev/serial/by-id/usb-radio')
            self.devices[0].fail = True
            current[0] = '/dev/ttyACM3'
            await asyncio.sleep(.1)
            self.assertTrue(api.system_status['connected'])
            self.assertEqual(api.serial_manager.port, '/dev/serial/by-id/usb-radio')

    async def test_rc_websocket_disconnect_revokes_owner(self):
        import json
        from fastapi import WebSocketDisconnect
        await self.connect()
        api.injector.enabled = True
        safe = dict(enumerate(api.injector.failsafe_us, 1))
        class Socket:
            epoch = None
            calls = 0
            async def accept(self):
                pass
            async def receive_text(self):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps({'action': 'acquire', 'channels': safe})
                if self.calls == 2:
                    return json.dumps({'epoch': self.epoch, 'channels': {**safe, 3: 1700}})
                raise WebSocketDisconnect()
            async def send_text(self, value):
                self.epoch = json.loads(value).get('epoch', self.epoch)
        self.devices[0].write = lambda frame: len(frame)
        await api.rc_websocket(Socket())
        self.assertIsNone(api.injector.owner)
        self.assertTrue(api.injector.failsafe_active)
        self.assertEqual(api.injector._channels_us[2], 988)

    async def test_empty_port_list(self):
        with patch.object(api.list_ports, 'comports', return_value=[]):
            self.assertEqual((await self.client.get('/api/serial/ports')).json()['ports'], [])
            self.assertEqual((await self.connect()).status_code, 400)


if __name__ == '__main__':
    unittest.main()
