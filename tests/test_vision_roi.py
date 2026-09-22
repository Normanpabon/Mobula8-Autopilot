import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from vision_roi import RegionSelection
from vision_pipeline import VisionPipeline
import elrs_backend as api


from vision_model import Detection
from vision_config import VisionConfig

class Model:
    is_loaded = True
    inference_ms = 1
    def __init__(self):
        self.frames = []
        self.boxes = []
        self.config = VisionConfig(pipeline_mode='segment')
    @property
    def status(self):
        return {'mode': self.config.pipeline_mode}
    def infer(self, frame):
        self.frames.append(frame.copy())
        return [Detection(0, 'obstacle', .9, box, np.full(frame.shape[:2], 255, np.uint8)
                          if self.config.pipeline_mode == 'segment' else None) for box in self.boxes]
    def is_available(self):
        return True


class ROITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'roi.json'
        self.pipeline = VisionPipeline(self.path)
        self.addCleanup(self.pipeline._executor.shutdown)
        self.pipeline.model = Model()
        self.pipeline.config = self.pipeline.model.config
        self.pipeline._model_state = (self.pipeline.model, 0)
        self.pipeline._running = True

    def select(self, indices):
        self.pipeline.set_roi([i in indices for i in range(96)])

    async def test_crop_masks_single_model_translates_boxes_and_clips_segmentation(self):
        # Envelope at x=20,y=20, with a hole at x=30..39.
        self.select({26, 28})
        frame = np.full((80,120,3), 200, np.uint8)
        self.pipeline.model.boxes = [[0,0,10,10], [10,0,20,10], [20,0,30,10]]
        result = self.pipeline._process(frame)
        for stage in [self.pipeline.model]:
            self.assertEqual(stage.frames[-1].shape, (10,30,3))
            self.assertTrue(np.all(stage.frames[-1][:,10:20] == 0))
            self.assertTrue(np.all(stage.frames[-1][:,:10] == 200))
        self.assertEqual([d['bbox'] for d in result.detections], [[20,20,30,30],[40,20,50,30]])
        self.assertEqual(result.region_count, 4)
        mask = np.zeros((80,120),np.uint8)
        cv2.drawContours(mask,result.contours,-1,255,-1)
        self.assertEqual(np.count_nonzero(mask[:,30:40]),0)
        self.assertTrue(np.all(frame == 200))
        self.pipeline._publish(result)
        self.assertEqual(self.pipeline.status['detection']['detections'],result.detections)

    async def test_empty_selection_pauses_both_stages_and_clears_old_result(self):
        self.pipeline._publish(self.pipeline._process(np.ones((80,120,3),np.uint8)))
        self.select(set())
        count = len(self.pipeline.model.frames)
        self.pipeline._process(np.ones((80,120,3),np.uint8))
        self.assertFalse(self.pipeline.active)
        self.assertIsNone(self.pipeline._latest)
        self.assertEqual(len(self.pipeline.model.frames),count)
        self.assertEqual(self.pipeline.status['detection']['detections'],[])

    async def test_inflight_old_selection_cannot_publish(self):
        old = self.pipeline._process(np.ones((80,120,3),np.uint8))
        self.select({0})
        self.pipeline._publish(old)
        self.assertIsNone(self.pipeline._latest)

    async def test_resolution_and_persistence(self):
        self.select({0,95})
        selection = RegionSelection.load(self.path)
        for h,w in [(480,720),(1080,1920),(481,641)]:
            mask=selection.mask(h,w)
            self.assertEqual(mask.shape,(h,w))
            self.assertEqual(mask[0,0],255)
            self.assertEqual(mask[-1,-1],255)
            self.assertEqual(mask[h//2,w//2],0)

    async def test_detector_only_uses_selection(self):
        self.select({0})
        self.pipeline.config.pipeline_mode = 'detect'
        self.pipeline.model.boxes=[[0,0,10,10]]
        result=self.pipeline._process(np.full((80,120,3),100,np.uint8))
        self.assertEqual(len(result.detections),1)
        self.assertEqual(self.pipeline.model.frames[-1].shape,(10,10,3))
        self.assertFalse(result.seg_used)

    async def test_api_validation_and_failed_save_keep_selection(self):
        with patch.object(api,'video',SimpleNamespace(vision=self.pipeline)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test') as client:
                for cells in [[],[True]*95,[1]*96,['yes']*96]:
                    self.assertEqual((await client.post('/api/vision/roi',json={'cells':cells})).status_code,422)
                self.assertEqual((await client.post('/api/vision/roi',json={'cells':[False]*96})).status_code,200)
                self.assertEqual((await client.get('/api/vision/roi')).json()['selected_count'],0)
                with patch.object(RegionSelection,'save',side_effect=OSError):
                    self.assertEqual((await client.post('/api/vision/roi',json={'cells':[True]*96})).status_code,500)
                self.assertEqual(self.pipeline.roi_status['selected_count'],0)
