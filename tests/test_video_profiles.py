"""Profile negotiation and end-to-end geometry using synthetic camera frames."""
import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import video_streamer as vs
import elrs_backend as api


class Camera:
    def __init__(self, size=(1080, 1920), fps=30):
        self.size, self.fps = size, fps
        self.settings = {}
        self.released = False
    def isOpened(self):
        return True
    def set(self, prop, value):
        self.settings[prop] = value
        return True
    def get(self, prop):
        return self.fps if prop == cv2.CAP_PROP_FPS else self.settings.get(prop, 0)
    def read(self):
        time.sleep(.002)
        return True, np.full((*self.size, 3), 90, dtype=np.uint8)
    def release(self):
        self.released = True


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for target, value in [('VIDEO_DIR', Path(self.directory.name)),
                              ('load_video_config', lambda: {'brightness':64, 'contrast':54, 'saturation':128, 'gamma':.9})]:
            p = patch.object(vs, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.stream = vs.VideoStreamer()
        self.stream.vision = None
        self.addAsyncCleanup(self.stream.stop_capture)

    async def test_digital_1080_preserves_track_recording_and_neutral_color(self):
        device = Camera()
        with patch.object(vs, '_open_capture', return_value=device):
            self.assertTrue(await self.stream.start_capture(profile='digital'))
        self.assertEqual((self.stream.capture.width, self.stream.capture.height), (1920, 1080))
        self.assertEqual(self.stream.capture._cfg['gamma'], 1)
        self.assertNotIn(cv2.CAP_PROP_BRIGHTNESS, device.settings)
        self.assertNotIn(cv2.CAP_PROP_SATURATION, device.settings)
        self.assertEqual(device.settings[cv2.CAP_PROP_FOURCC], cv2.VideoWriter_fourcc(*'MJPG'))
        track = vs.FPVVideoTrack(self.stream.capture.get_frame, 1920, 1080, 30)
        frame = await track.recv()
        self.assertEqual((frame.width, frame.height), (1920, 1080))
        path = await self.stream.start_recording('hd')
        await asyncio.sleep(.15)
        await self.stream.stop_recording()
        reader = cv2.VideoCapture(path)
        try:
            ok, frame = reader.read()
            self.assertTrue(ok)
            self.assertEqual(frame.shape[:2], (1080, 1920))
        finally:
            reader.release()

    async def test_mjpeg_rejected_and_best_real_mode_selected(self):
        created = []
        class Webcam(Camera):
            def read(self):
                if cv2.CAP_PROP_FOURCC in self.settings:
                    return False, None
                self.size = (720, 1280) if self.settings.get(cv2.CAP_PROP_FRAME_WIDTH) == 1280 else (480, 640)
                return super().read()
        def factory(_):
            device = Webcam()
            created.append(device)
            return device
        with patch.object(vs, '_open_capture', side_effect=factory):
            self.assertTrue(await self.stream.start_capture(profile='digital'))
        self.assertEqual((self.stream.capture.width, self.stream.capture.height), (1280, 720))
        self.assertTrue(all(cam.released for cam in created[:-1]))
        self.assertFalse(created[-1].released)
        self.assertIn('1920', self.stream.capture.format_warning)
        self.assertGreater(len(self.stream.capture.negotiation), 1)

    async def test_analog_pal_ntsc_keep_calibration_and_native_size(self):
        for standard, height, fps in [('ntsc',480,vs.NTSC_FPS), ('pal',576,25)]:
            device = Camera((height, 720), fps)
            with patch.object(vs, '_open_capture', return_value=device):
                self.assertTrue(await self.stream.start_capture(profile='analog', standard=standard))
            self.assertEqual(device.settings[cv2.CAP_PROP_FRAME_HEIGHT], height)
            self.assertEqual(device.settings[cv2.CAP_PROP_BRIGHTNESS], 64)
            self.assertNotIn(cv2.CAP_PROP_FOURCC, device.settings)
            self.assertEqual(self.stream.capture.fps, fps)

    async def test_profile_change_restarts_but_is_blocked_during_recording(self):
        with patch.object(vs, '_open_capture', side_effect=lambda _: Camera((480,720))):
            await self.stream.start_capture(profile='analog')
            task = self.stream.capture._task
            await self.stream.start_capture(profile='analog')
            self.assertIs(self.stream.capture._task, task)
            await self.stream.start_recording('profile')
            with self.assertRaisesRegex(RuntimeError, 'Detén'):
                await self.stream.start_capture(profile='digital')
            await self.stream.stop_recording()
            await self.stream.start_capture(profile='digital')
            self.assertIsNot(self.stream.capture._task, task)
            self.assertEqual(self.stream.capture.profile, 'digital')

    async def test_api_profiles_and_paired_dimensions(self):
        with patch.object(api, 'video', self.stream):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test') as client:
                for body in [{'profile':'other'}, {'width':1920}, {'height':1080}]:
                    self.assertEqual((await client.post('/api/video/start', json=body)).status_code, 422)
                digital = (await client.get('/api/video/config?profile=digital')).json()
                analog = (await client.get('/api/video/config?profile=analog')).json()
                self.assertEqual(digital['gamma'], 1)
                self.assertNotIn('brightness', digital)
                self.assertEqual(analog['brightness'], 64)
                device = Camera()
                with patch.object(vs, '_open_capture', return_value=device):
                    response = await client.post('/api/video/start', json={'profile':'digital'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['width'], 1920)
                self.assertTrue(response.json()['requested']['adaptive'])
