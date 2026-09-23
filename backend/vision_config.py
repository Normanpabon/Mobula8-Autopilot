"""Validated, mode-specific vision configuration (class names also support custom models)."""
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool

CONFIG_FILE = Path(__file__).parent / 'config' / 'vision.json'

class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Models(Settings):
    detect: str = Field(default='yolo26n.pt', min_length=1)
    segment: str = Field(default='yolo26n-seg.pt', min_length=1)

class Sizes(Settings):
    detect: int = Field(default=640, ge=32, le=2048, strict=True)
    segment: int = Field(default=416, ge=32, le=2048, strict=True)

class Confidence(Settings):
    default: float = Field(default=.45, ge=0, le=1, allow_inf_nan=False)
    per_class: dict[str, float] = Field(default_factory=dict)

    def model_post_init(self, context):
        import math
        if any(not name or not math.isfinite(v) or not 0 <= v <= 1 for name, v in self.per_class.items()):
            raise ValueError('Thresholds deben estar entre 0 y 1 y tener nombre de clase')

class Classes(Settings):
    enabled: list[str] = Field(default_factory=lambda: ['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow'])

class Overlay(Settings):
    boxes: StrictBool = True
    labels: StrictBool = True
    masks: StrictBool = True

class Benchmark(Settings):
    collect_metrics: StrictBool = True
    window_seconds: int = Field(default=30, ge=1, le=3600, strict=True)

class VisionConfig(Settings):
    pipeline_mode: Literal['off', 'detect', 'segment'] = 'off'
    models: Models = Field(default_factory=Models)
    imgsz: Sizes = Field(default_factory=Sizes)
    confidence: Confidence = Field(default_factory=Confidence)
    coco_classes: Classes = Field(default_factory=Classes)
    overlay: Overlay = Field(default_factory=Overlay)
    benchmark: Benchmark = Field(default_factory=Benchmark)
    profiles: dict[Literal['analog', 'digital'], Sizes] = Field(default_factory=lambda: {
        'analog': Sizes(detect=416, segment=416), 'digital': Sizes(detect=640, segment=640)})

    @classmethod
    def load(cls, path=CONFIG_FILE):
        path = Path(path)
        return cls.model_validate_json(path.read_text()) if path.exists() else cls()

    def patched(self, patch):
        if not isinstance(patch, dict):
            raise ValueError('La configuración debe ser un objeto')
        patch = dict(patch)
        profile = patch.pop('profile', None)
        if profile is not None:
            if profile not in self.profiles:
                raise ValueError('Perfil de visión desconocido')
            patch.setdefault('imgsz', self.profiles[profile].model_dump())
        mode = patch.get('pipeline_mode', self.pipeline_mode)
        if isinstance(patch.get('imgsz'), int):
            if mode == 'off':
                raise ValueError('imgsz requiere modo detect o segment')
            patch['imgsz'] = {mode: patch['imgsz']}
        if 'enabled_classes' in patch:
            patch['coco_classes'] = {'enabled': patch.pop('enabled_classes')}
        data = self.model_dump()
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **value}
            else:
                data[key] = value
        return type(self).model_validate(data)

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.model_dump(), indent=2) + '\n')
        tmp.replace(path)
