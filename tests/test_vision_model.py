import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from vision_config import VisionConfig
from vision_model import VisionModel

class FakeYOLO:
    def __init__(self, path, task):
        self.task = task
        self.names = {0: 'person', 1: 'cow', 2: 'car'}
        self.calls = []
    def __call__(self, frame, **kwargs):
        self.calls.append(kwargs)
        boxes = [SimpleNamespace(cls=[idx], conf=[score], xyxy=np.array([[1., 1., 8., 8.]]))
                 for idx, score in [(0, .49), (1, .41), (2, .99)]]
        polygons = [np.array([[1,1],[8,1],[8,8],[1,8]])] * 3
        return [SimpleNamespace(names=self.names, boxes=boxes,
                                masks=SimpleNamespace(xy=polygons) if self.task == 'segment' else None)]

def config(mode='detect'):
    return VisionConfig().patched({'pipeline_mode': mode, 'enabled_classes': ['person', 'cow'],
                                   'confidence': {'default': .45, 'per_class': {'person': .5, 'cow': .4}}})

class ModelTests(unittest.TestCase):
    def test_single_call_thresholds_classes_and_masks(self):
        for mode in ['detect', 'segment']:
            with self.subTest(mode=mode):
                model = VisionModel(config(mode), FakeYOLO)
                model.load()
                model._model.calls.clear()  # Warm-up is not a frame inference.
                detections = model.infer(np.zeros((10, 20, 3), np.uint8))
                self.assertEqual(len(model._model.calls), 1)
                self.assertEqual(model._model.calls[0]['conf'], .4)
                self.assertEqual(model._model.calls[0]['classes'], [0, 1])
                self.assertEqual([d.class_name for d in detections], ['cow'])
                self.assertEqual(detections[0].mask is None, mode == 'detect')
                if mode == 'segment':
                    self.assertEqual(detections[0].mask.shape, (10,20))
                    self.assertEqual(detections[0].mask[9,19], 0)
    def test_empty_classes_skip_inference(self):
        model = VisionModel(config().patched({'enabled_classes': []}), FakeYOLO)
        model.load()
        model._model.calls.clear()
        self.assertEqual(model.infer(np.zeros((10,10,3),np.uint8)), [])
        self.assertEqual(model._model.calls, [])
    def test_unknown_class_and_wrong_task_rejected(self):
        with self.assertRaises(ValueError):
            VisionModel(config().patched({'enabled_classes':['tractor']}), FakeYOLO).load()
        def wrong(path, task):
            return FakeYOLO(path, 'segment')
        with self.assertRaises(ValueError):
            VisionModel(config(), wrong).load()
    def test_off_never_loads(self):
        model = VisionModel(config('off'), FakeYOLO)
        model.load()
        self.assertFalse(model.is_loaded)
        self.assertEqual(model.infer(np.zeros((10,10,3),np.uint8)), [])
