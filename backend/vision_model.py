"""Single Ultralytics model; each infer call produces boxes and optional masks."""
from dataclasses import dataclass
from pathlib import Path
import importlib.util
import time
import cv2
import numpy as np
from vision_config import VisionConfig

MODELS_DIR = Path(__file__).resolve().parents[1] / 'models'

@dataclass
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: list[float]
    mask: np.ndarray | None = None

class VisionModel:
    def __init__(self, config=None, factory=None):
        self.config = config or VisionConfig()
        self._factory = factory
        self._model = None
        self.enabled_ids = []
        self.inference_ms = 0.0
        self.model_load_ms = 0.0
        self.warmup_ms = 0.0

    def is_available(self):
        return self._factory is not None or importlib.util.find_spec('ultralytics') is not None

    @property
    def is_loaded(self):
        return self._model is not None

    def load(self):
        mode = self.config.pipeline_mode
        if mode == 'off':
            return
        factory = self._factory
        if factory is None:
            from ultralytics import YOLO
            factory = YOLO
        name = getattr(self.config.models, mode)
        local = MODELS_DIR / name
        t0 = time.perf_counter()
        model = factory(str(local) if local.exists() else name, task=mode)
        if model.task != mode:
            raise ValueError(f'El modelo tiene task={model.task}, se requiere {mode}')
        names = model.names
        names = dict(enumerate(names)) if isinstance(names, list) else names
        requested = set(self.config.coco_classes.enabled) | set(self.config.confidence.per_class)
        unknown = requested - set(names.values())
        if unknown:
            raise ValueError(f'Clases inexistentes en el modelo: {sorted(unknown)}')
        self.enabled_ids = [idx for idx, name in names.items() if name in self.config.coco_classes.enabled]
        self.model_load_ms = (time.perf_counter() - t0) * 1000
        size = getattr(self.config.imgsz, mode)
        t0 = time.perf_counter()
        model(np.zeros((size, size, 3), np.uint8), imgsz=size, verbose=False)
        self.warmup_ms = (time.perf_counter() - t0) * 1000
        self._model = model

    def infer(self, frame):
        if not self.is_loaded or self.config.pipeline_mode == 'off' or not self.enabled_ids:
            self.inference_ms = 0.0
            return []
        mode = self.config.pipeline_mode
        confidence = self.config.confidence
        t0 = time.perf_counter()
        result = self._model(frame, imgsz=getattr(self.config.imgsz, mode),
                             conf=min([confidence.default, *confidence.per_class.values()]),
                             classes=self.enabled_ids, verbose=False)[0]
        detections = []
        # masks.xy already undoes letterboxing and returns original image coordinates.
        polygons = result.masks.xy if mode == 'segment' and result.masks is not None else []
        for i, box in enumerate(result.boxes):
            class_id, score = int(box.cls[0]), float(box.conf[0])
            name = result.names[class_id]
            if class_id not in self.enabled_ids or score < confidence.per_class.get(name, confidence.default):
                continue
            mask = None
            if i < len(polygons):
                mask = np.zeros(frame.shape[:2], np.uint8)
                cv2.fillPoly(mask, [np.asarray(polygons[i], dtype=np.int32)], 255)
            detections.append(Detection(class_id, name, score, box.xyxy[0].tolist(), mask))
        self.inference_ms = (time.perf_counter() - t0) * 1000
        return detections

    @property
    def status(self):
        mode = self.config.pipeline_mode
        return {'mode': mode, 'model': getattr(self.config.models, mode) if mode != 'off' else None,
                'imgsz': getattr(self.config.imgsz, mode) if mode != 'off' else None,
                'model_loaded': self.is_loaded, 'enabled_classes': list(self.config.coco_classes.enabled),
                'confidence': self.config.confidence.model_dump(), 'inference_ms': self.inference_ms}

    @staticmethod
    def list_local_models(task):
        return sorted(p.name for p in MODELS_DIR.glob('*')
                      if p.suffix in ('.pt', '.onnx', '.engine') and ('-seg' in p.stem) == (task == 'segment'))
