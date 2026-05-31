"""
YOLOProcessor — Inferencia de visión en tiempo real sobre frames FPV
=====================================================================
Integra con video_streamer.py como paso opcional en el pipeline de frames.

Dependencias:
    pip install ultralytics   (incluye torch CPU por defecto)
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118  (GPU CUDA 11.8)

Modelos:
    - Colocar archivos .pt en la carpeta models/ para uso offline.
    - Si el modelo no está localmente, ultralytics lo descarga automáticamente.
    - Defaults disponibles: yolov8n.pt (~6MB), yolov8s.pt (~22MB), yolov8m.pt (~50MB)
"""

import asyncio
import concurrent.futures
import time
import logging
from pathlib import Path
from typing import Optional
import numpy as np

log = logging.getLogger("yolo_processor")

MODELS_DIR = Path(__file__).parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False
    log.warning("[YOLO] ultralytics no instalado — pip install ultralytics")


class YOLOProcessor:
    """
    Procesa frames BGR con un modelo YOLO y devuelve frames anotados.
    La inferencia corre en un ThreadPoolExecutor de 1 worker para no
    bloquear el event loop de asyncio.
    """

    def __init__(self):
        self._model           = None
        self._model_path:  Optional[str] = None
        self._executor        = concurrent.futures.ThreadPoolExecutor(max_workers=1,
                                                                       thread_name_prefix="yolo")
        self.enabled          = False
        self.confidence       = 0.5
        self._inf_fps         = 0.0
        self._last_detections: list = []

    # ── API pública ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return ULTRALYTICS_AVAILABLE

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
            # Warm-up
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            model(dummy, verbose=False)
            self._model      = model
            self._model_path = model_name
            log.info(f"[YOLO] Modelo {model_name} listo")
            return True
        except Exception as e:
            log.error(f"[YOLO] Error cargando {model_name}: {e}")
            self._model = None
            return False

    async def process_async(self, frame_bgr: np.ndarray) -> np.ndarray:
        """
        Corre inferencia en el executor y devuelve el frame anotado (BGR).
        Si YOLO no está listo, devuelve el frame original sin modificar.
        """
        if not self._model or not self.enabled:
            return frame_bgr
        loop = asyncio.get_event_loop()
        try:
            annotated, _ = await loop.run_in_executor(
                self._executor, self._infer, frame_bgr
            )
            return annotated
        except Exception as e:
            log.error(f"[YOLO] Error de inferencia: {e}")
            return frame_bgr

    # ── Internals ────────────────────────────────────────────────────────────

    def _infer(self, frame_bgr: np.ndarray) -> tuple:
        """Inferencia síncrona + dibujo de bounding boxes."""
        t0 = time.perf_counter()
        results = self._model(frame_bgr, conf=self.confidence, verbose=False)
        dt = time.perf_counter() - t0
        self._inf_fps = round(1.0 / dt, 1) if dt > 0 else 0

        # results[0].plot() devuelve BGR con cajas y labels dibujados
        annotated = results[0].plot()

        detections = []
        for box in results[0].boxes:
            detections.append({
                "class":      results[0].names[int(box.cls[0])],
                "confidence": round(float(box.conf[0]), 2),
                "bbox":       [round(x, 1) for x in box.xyxy[0].tolist()],
            })
        self._last_detections = detections
        return annotated, detections

    @property
    def status(self) -> dict:
        return {
            "available":       ULTRALYTICS_AVAILABLE,
            "model_loaded":    self._model is not None,
            "model_path":      self._model_path,
            "enabled":         self.enabled,
            "confidence":      self.confidence,
            "inf_fps":         self._inf_fps,
            "detection_count": len(self._last_detections),
            "detections":      self._last_detections,
        }

    @staticmethod
    def list_local_models() -> list[str]:
        """Lista archivos .pt en la carpeta models/."""
        return sorted(f.name for f in MODELS_DIR.glob("*.pt"))
