"""Real weights compatibility test (downloads weights when absent)."""
import sys
from pathlib import Path
import cv2
from ultralytics.utils import ASSETS
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from vision_config import VisionConfig
from vision_model import VisionModel

frame = cv2.imread(str(ASSETS / 'bus.jpg'))
assert frame is not None
for mode in ('detect','segment'):
    model=VisionModel(VisionConfig(pipeline_mode=mode))
    model.load()
    detections = model.infer(frame)
    assert detections, f"Sin cajas en {mode}"
    if mode == "segment":
        assert any(d.mask is not None and d.mask.any() for d in detections)
    assert model.is_loaded and model.inference_ms > 0
    print(model.status)
