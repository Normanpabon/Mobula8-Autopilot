"""Regresiones de formato y persistencia; frames sintéticos, sin hardware."""
import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import cv2
import numpy as np
import httpx
import video_streamer as vs
import elrs_backend as api


class CaptureDevice:
    def __init__(self, fps=vs.NTSC_FPS, failures=0):
        self.fps, self.failures = fps, failures
        self.frame = np.full((480, 720, 3), 90, dtype=np.uint8)
        self.released = False
        self.settings = {}

    def isOpened(self):
        return True

    def set(self, prop, value):
        self.settings[prop] = value
        return True

    def get(self, prop):
        return self.fps if prop == cv2.CAP_PROP_FPS else 0

    def read(self):
        time.sleep(.002)
        if self.failures:
            self.failures -= 1
            return False, None
        return True, self.frame.copy()

    def release(self):
        self.released = True


class VideoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        p = patch.object(vs, 'VIDEO_DIR', self.folder)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(vs, 'load_video_config', return_value={'ntsc': True, 'gamma': 1})
        p.start()
        self.addCleanup(p.stop)
        self.stream = vs.VideoStreamer()
        self.stream.vision = None
        self.addAsyncCleanup(self.stream.stop_capture)

    async def open_capture(self, fps=vs.NTSC_FPS, failures=0):
        device = CaptureDevice(fps, failures)
        with patch.object(vs, '_open_capture', return_value=device):
            self.assertTrue(await self.stream.start_capture(0, 1280, 720, vs.NTSC_FPS))
        return device

    async def test_negotiated_format_reaches_track_and_recorder(self):
        await self.open_capture(failures=2)
        status = self.stream.capture.status
        self.assertEqual((status['width'], status['height']), (720, 480))
        self.assertEqual(status['requested']['width'], 1280)
        self.assertEqual(status['fps_source'], 'driver')
        self.assertTrue(status['format_warning'])
        manager = self.stream.webrtc
        self.assertEqual((manager._width, manager._height), (720, 480))
        track = vs.FPVVideoTrack(self.stream.capture.get_frame, 720, 480, vs.NTSC_FPS)
        first, second = await track.recv(), await track.recv()
        self.assertEqual((first.width, first.height), (720, 480))
        self.assertAlmostEqual(float((second.pts-first.pts)*second.time_base), 1/vs.NTSC_FPS, places=4)
        path = await self.stream.start_recording('test')
        await asyncio.sleep(.18)
        await self.stream.stop_recording()
        reader = cv2.VideoCapture(path)
        try:
            ok, frame = reader.read()
            self.assertTrue(ok)
            self.assertEqual(frame.shape[:2], (480, 720))
            self.assertGreaterEqual(reader.get(cv2.CAP_PROP_FRAME_COUNT), 3)
        finally:
            reader.release()

    async def test_invalid_driver_fps_falls_back_without_nan(self):
        await self.open_capture(fps=float('nan'))
        self.assertEqual(self.stream.capture.fps, vs.NTSC_FPS)
        self.assertEqual(self.stream.capture.fps_source, 'requested_fallback')

    async def test_read_failure_releases_device(self):
        device = CaptureDevice(failures=100)
        with patch.object(vs, '_open_capture', return_value=device):
            self.assertFalse(await self.stream.capture.start())
        self.assertTrue(device.released)
        self.assertFalse(self.stream.capture.is_running)
        self.assertIsNone(await self.stream.capture.get_frame())

    async def test_unique_takes_and_idempotent_start(self):
        await self.open_capture()
        first = await self.stream.start_recording('same_session')
        task = self.stream._record_task
        self.assertEqual(await self.stream.start_recording('same_session'), first)
        self.assertIs(self.stream._record_task, task)
        await asyncio.sleep(.08)
        await self.stream.stop_recording()
        original = Path(first).read_bytes()
        second = await self.stream.start_recording('same_session')
        await asyncio.sleep(.08)
        await self.stream.stop_recording()
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first).read_bytes(), original)
        self.assertTrue(task.done())

    async def test_capture_change_during_recording_rejected(self):
        await self.open_capture()
        await self.stream.start_recording('test')
        self.assertTrue(await self.stream.start_capture(0, 1280, 720, vs.NTSC_FPS))
        with self.assertRaisesRegex(RuntimeError, 'Detén'):
            await self.stream.start_capture(0, 640, 480, vs.NTSC_FPS)

    async def test_stop_capture_finalizes_file(self):
        device = await self.open_capture()
        path = await self.stream.start_recording('test')
        await asyncio.sleep(.08)
        await self.stream.stop_capture()
        self.assertTrue(device.released)
        self.assertFalse(self.stream.recorder.is_recording)
        self.assertIsNone(self.stream._record_task)
        reader = cv2.VideoCapture(path)
        try:
            self.assertTrue(reader.read()[0])
        finally:
            reader.release()

    async def test_encoder_failure_not_reported_as_recording(self):
        await self.open_capture()
        writer = MagicMock()
        writer.isOpened.return_value = False
        with patch.object(vs.cv2, 'VideoWriter', return_value=writer):
            with self.assertRaisesRegex(RuntimeError, 'encoder'):
                await self.stream.start_recording('test')
        self.assertFalse(self.stream.recorder.is_recording)
        self.assertIsNone(self.stream._record_task)
        self.assertEqual(writer.release.call_count, 2)

    async def test_size_mismatch_closes_recording_with_error(self):
        await self.open_capture()
        await self.stream.start_recording('test')
        async def wrong_frame():
            return np.zeros((240, 320, 3), dtype=np.uint8)
        with patch.object(self.stream.capture, 'get_frame', side_effect=wrong_frame):
            await asyncio.sleep(.06)
        self.assertFalse(self.stream.recorder.is_recording)
        self.assertIn('tamaño', self.stream.recorder.error)

    async def test_api_reports_actual_dimensions_and_validates_fps(self):
        device = CaptureDevice()
        with patch.object(api, 'video', self.stream), patch.object(vs, '_open_capture', return_value=device):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test') as client:
                response = await client.post('/api/video/start', json={'width':1280, 'height':720, 'fps':29.97})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['width'], 720)
                self.assertEqual(response.json()['requested']['width'], 1280)
                self.assertAlmostEqual(response.json()['fps'], vs.NTSC_FPS)
                response = await client.post('/api/video/start', json={'fps':0})
                self.assertEqual(response.status_code, 422)
                response = await client.post('/api/video/start', json={'width':-1})
                self.assertEqual(response.status_code, 422)

    async def test_shutdown_finalizes_recording(self):
        await self.open_capture()
        async def no_serial(*args):
            return
        with patch.object(api, 'video', self.stream), patch.object(api, 'serial_reader_task', no_serial):
            async with api.lifespan(api.app):
                path = await self.stream.start_recording('shutdown')
                await asyncio.sleep(.08)
        reader = cv2.VideoCapture(path)
        try:
            self.assertTrue(reader.read()[0])
        finally:
            reader.release()


if __name__ == '__main__':
    unittest.main()
