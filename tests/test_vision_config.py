import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from vision_config import VisionConfig, CONFIG_FILE

class ConfigTests(unittest.TestCase):
    def test_json_and_defaults(self):
        self.assertEqual(VisionConfig().models.detect, 'yolo26n.pt')
        self.assertEqual(VisionConfig().pipeline_mode, 'off')
        self.assertEqual(VisionConfig.load(CONFIG_FILE).models.segment, 'yolo26n-seg.pt')
        self.assertEqual(VisionConfig().patched({}), VisionConfig())
    def test_profile_presets(self):
        self.assertEqual(VisionConfig().patched({'profile':'analog'}).imgsz.detect,416)
        self.assertEqual(VisionConfig().patched({'profile':'digital'}).imgsz.segment,640)
        with self.assertRaises(ValueError):
            VisionConfig().patched({'profile':'unknown'})

    def test_invalid_values(self):
        for patch in [{'pipeline_mode':'both'}, {'imgsz': 0}, {'imgsz': True},
                      {'confidence':{'default':float('nan')}}, {'confidence':{'per_class':{'cow':2}}},
                      {'unknown':True}, {'overlay':{'masks':'yes'}}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                VisionConfig().patched(patch)
    def test_patch_preserves_other_mode_and_replaces_thresholds(self):
        c = VisionConfig().patched({'pipeline_mode':'detect', 'imgsz':416, 'enabled_classes':['person']})
        self.assertEqual(c.imgsz.detect,416)
        self.assertEqual(c.imgsz.segment,416)
        c = c.patched({'confidence':{'per_class':{'person':.7}}})
        self.assertEqual(c.patched({'confidence':{'per_class':{}}}).confidence.per_class,{})
