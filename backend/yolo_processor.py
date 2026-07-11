"""
YOLOProcessor — Detección de objetos sobre frames FPV
=====================================================
Wrapper síncrono del modelo de detección YOLO. Desde v2.6.0 el threading y
la orquestación viven en `vision_pipeline.py` (un solo worker para toda la
cascada segmentación → detección); este módulo solo carga el modelo y corre
inferencia bloqueante.

Dependencias:
    pip install ultralytics   (incluye torch CPU por defecto)
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118  (GPU CUDA 11.8)

Modelos:
    - Colocar archivos .pt / .onnx / .engine en la carpeta models/ para uso offline.
    - Si el modelo no está localmente, ultralytics lo descarga automáticamente.
    - Defaults disponibles: yolov8n.pt (~6MB), yolov8s.pt (~22MB), yolov8m.pt (~50MB)
    - Modelos fine-tuneados propios: ver docs/YOLO_FINETUNING.md
"""

import time
import logging
from pathlib import Path
from typing import Optional
import numpy as np

log = logging.getLogger("yolo_processor")

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False
    log.warning("[YOLO] ultralytics no instalado — pip install ultralytics")


class YOLOProcessor:
    """
    Detección de objetos sobre frames BGR. `infer()` es bloqueante: llamarlo
    siempre desde el worker de VisionPipeline, nunca desde el event loop.
    """

    def __init__(self):
        self._model           = None
        self._model_path:  Optional[str] = None
        self.enabled          = False
        self.confidence       = 0.5
        self.imgsz            = 640   # 640 default; 416/320 reducen latencia (ver YOLO_FINETUNING.md)
        self._inf_ms          = 0.0
        self._inf_fps         = 0.0
        self._last_detections: list = []

    # ── API pública ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return ULTRALYTICS_AVAILABLE

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load_model(self, model_name: str = "yolov8n.pt") -> bool:
        """
        Carga el modelo YOLO.  Busca primero en models/, luego descarga.
        Hace warm-up con un frame negro para evitar latencia en el primer frame real.
        Bloqueante — llamar siempre desde run_in_executor.
        """
        if not ULTRALYTICS_AVAILABLE:
            log.error("[YOLO] ultralytics no instalado")
            return False

        local = MODELS_DIR / model_name
        path  = str(local) if local.exists() else model_name

        try:
            log.info(f"[YOLO] Cargando modelo: {path}")
            model = YOLO(path)
            # Warm-up al imgsz configurado
            dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
            model(dummy, imgsz=self.imgsz, verbose=False)
            self._model      = model
            self._model_path = model_name
            log.info(f"[YOLO] Modelo {model_name} listo (imgsz={self.imgsz})")
            return True
        except Exception as e:
            log.error(f"[YOLO] Error cargando {model_name}: {e}")
            self._model = None
            return False

    def infer(self, frame_bgr: np.ndarray) -> list:
        """
        Inferencia síncrona. Devuelve la lista de detecciones:
        [{"class": str, "confidence": float, "bbox": [x1, y1, x2, y2]}, ...]
        Las coordenadas están en píxeles del frame original.
        """
        if self._model is None:
            return []

        t0 = time.perf_counter()
        results = self._model(frame_bgr, conf=self.confidence,
                              imgsz=self.imgsz, verbose=False)
        dt = time.perf_counter() - t0
        self._inf_ms  = round(dt * 1000, 1)
        self._inf_fps = round(1.0 / dt, 1) if dt > 0 else 0.0

        detections = []
        for box in results[0].boxes:
            detections.append({
                "class":      results[0].names[int(box.cls[0])],
                "confidence": round(float(box.conf[0]), 2),
                "bbox":       [round(x, 1) for x in box.xyxy[0].tolist()],
            })
        self._last_detections = detections
        return detections

    @property
    def status(self) -> dict:
        return {
            "available":       ULTRALYTICS_AVAILABLE,
            "model_loaded":    self._model is not None,
            "model_path":      self._model_path,
            "enabled":         self.enabled,
            "confidence":      self.confidence,
            "imgsz":           self.imgsz,
            "inf_ms":          self._inf_ms,
            "inf_fps":         self._inf_fps,
            "detection_count": len(self._last_detections),
            "detections":      self._last_detections,
        }

    @staticmethod
    def list_local_models() -> list:
        """
        Modelos de detección en models/ (.pt/.onnx/.engine).
        Excluye los de segmentación (convención: contienen "-seg").
        """
        exts = ("*.pt", "*.onnx", "*.engine")
        names = []
        for ext in exts:
            names.extend(f.name for f in MODELS_DIR.glob(ext))
        return sorted(n for n in set(names) if "-seg" not in n)
