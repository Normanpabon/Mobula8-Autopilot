import sys
import asyncio
import threading
import tempfile
import time
import unittest
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from vision_pipeline import VisionPipeline, VisionResult, LatencyGovernor
from vision_config import VisionConfig
from test_vision_model import FakeYOLO, config
import elrs_backend as api

class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'vision.json'
        config('off').save(self.path)
        self.pipeline = VisionPipeline(Path(self.tmp.name)/'roi.json', self.path, FakeYOLO)
        self.pipeline._running = True
        self.addCleanup(self.pipeline._executor.shutdown)
        self.frame = np.ones((80,120,3),np.uint8)
    async def test_single_inference_modes_release_and_reject_old_results(self):
        previous = None
        for mode in ['detect','segment','detect','off']:
            await self.pipeline.configure({'pipeline_mode':mode})
            if previous is not None:
                self.assertIsNone(previous())
            if mode != 'off':
                self.pipeline.model._model.calls.clear()
                previous = weakref.ref(self.pipeline.model._model)
            result = self.pipeline._process(self.frame)
            if mode != 'off':
                self.assertEqual(len(self.pipeline.model._model.calls),1)
                self.assertEqual(len(result.detections),1)
                self.assertEqual(bool(result.contours), mode == 'segment')
            else:
                self.assertEqual(result.detections,[])
            self.pipeline._publish(result)
        await self.pipeline.configure({'pipeline_mode':'detect'})
        self.pipeline._publish(result)
        self.assertIsNone(self.pipeline._latest)
    async def test_switch_during_inference_serializes_and_invalidates_result(self):
        await self.pipeline.configure({'pipeline_mode':'detect'})
        entered, release = threading.Event(), threading.Event()
        original = self.pipeline.model.infer
        def slow(frame):
            entered.set()
            if not release.wait(2):
                raise TimeoutError('test worker timeout')
            return original(frame)
        self.pipeline.model.infer = slow
        loop = asyncio.get_running_loop()
        old = loop.run_in_executor(self.pipeline._executor, self.pipeline._process, self.frame)
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(.005)
            self.assertTrue(entered.is_set())
            switch = asyncio.create_task(self.pipeline.configure({'pipeline_mode':'segment'}))
            # Overlay remains synchronous and never waits for the worker.
            self.pipeline.annotate(self.frame.copy())
            await asyncio.sleep(.01)
            self.assertFalse(switch.done())
        finally:
            release.set()
        result = await old
        await switch
        self.pipeline._publish(result)
        self.assertIsNone(self.pipeline._latest)
        self.assertEqual(self.pipeline.status['mode'],'segment')

    async def test_metrics_reset_and_loading_governor(self):
        await self.pipeline.configure({'pipeline_mode':'detect'})
        self.assertEqual(self.pipeline.status['governor']['mode'],'warming_up')
        self.pipeline._publish(self.pipeline._process(self.frame))
        self.assertEqual(self.pipeline.status['metrics']['samples'],1)
        self.assertIsNotNone(self.pipeline.status['metrics']['pipeline_ms']['p95'])
        await self.pipeline.configure({'pipeline_mode':'off'})
        self.assertEqual(self.pipeline.status['metrics']['samples'],0)
        self.assertEqual(self.pipeline.status['governor']['mode'],'off')
        await self.pipeline.configure({'pipeline_mode':'detect', 'enabled_classes':[]})
        self.assertFalse(self.pipeline.active)
        self.assertEqual(self.pipeline.status['governor']['mode'],'warming_up')
        self.assertEqual(self.pipeline.status['governor']['max_speed_ms'],0)

    async def test_failures_preserve_config_model_and_file(self):
        await self.pipeline.configure({'pipeline_mode':'detect'})
        model = self.pipeline.model
        content = self.path.read_text()
        with self.assertRaises(ValueError):
            await self.pipeline.configure({'enabled_classes':['invalid']})
        with patch.object(VisionConfig,'save',side_effect=OSError), self.assertRaises(OSError):
            await self.pipeline.configure({'pipeline_mode':'off'})
        self.assertIs(self.pipeline.model,model)
        self.assertEqual(self.path.read_text(),content)
    async def test_api_and_legacy_routes_are_exclusive(self):
        with patch.object(api,'video',SimpleNamespace(vision=self.pipeline, yolo=self.pipeline.model)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test') as c:
                for route, body, mode in [('/api/vision/config',{'pipeline_mode':'detect'},'detect'),
                                          ('/api/segmentation/config',{'enabled':True},'segment'),
                                          ('/api/yolo/config',{'enabled':True},'detect'),
                                          ('/api/vision/config',{'pipeline_mode':'off'},'off')]:
                    r=await c.post(route,json=body)
                    self.assertEqual(r.status_code,200,r.text)
                    self.assertEqual((await c.get('/api/vision/status')).json()['mode'],mode)
                for body in [{'pipeline_mode':'both'},{'imgsz':0},{'enabled_classes':['bad'],'pipeline_mode':'detect'}]:
                    self.assertEqual((await c.post('/api/vision/config',json=body)).status_code,422)
                self.assertEqual((await c.get('/api/vision/config')).json()['pipeline_mode'],'off')
    async def test_overlay_does_not_infer_and_stale_hovers(self):
        await self.pipeline.configure({'pipeline_mode':'segment'})
        self.pipeline._publish(self.pipeline._process(self.frame))
        count=len(self.pipeline.model._model.calls)
        self.pipeline.annotate(self.frame.copy())
        self.assertEqual(len(self.pipeline.model._model.calls),count)
        self.pipeline._latest.ts=time.time()-10
        self.assertEqual(self.pipeline.status['governor']['mode'],'stale')
        self.assertEqual(self.pipeline.status['governor']['max_speed_ms'],0)
        await self.pipeline.stop()
        self.pipeline._publish(VisionResult(ts=time.time()))
        self.assertIsNone(self.pipeline._latest)
