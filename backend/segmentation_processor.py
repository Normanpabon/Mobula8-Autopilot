"""
SegmentationProcessor — Etapa opcional de segmentación previa a la detección
============================================================================
Primera etapa de la cascada de visión (ver `vision_pipeline.py`): un modelo
de segmentación de instancias (yolov8n-seg por defecto) genera una máscara
binaria con las regiones ocupadas por objetos. Usos:

- **focus_mode = "mask"**: el fondo se suprime (bitwise_and) antes de pasar
  el frame al detector YOLO. Reduce falsos positivos en fondos ruidosos
  (interferencia analógica de la EasyCap) a costa de ~1 inferencia extra.
- **focus_mode = "overlay"**: la máscara solo se dibuja en el stream, sin
  afectar al detector. Útil para evaluar la etapa antes de encadenarla.

La etapa se enciende/apaga con `enabled`, independiente del detector.
Modelos fine-tuneados propios: convención de nombre con "-seg"
(ej. `mobula-seg.pt`) para que aparezcan en la lista correcta.
"""

import time
import logging
from pathlib import Path
from typing import Optional
import numpy as np
import cv2

log = logging.getLogger("segmentation_processor")

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False
    log.warning("[SEG] ultralytics no instalado — pip install ultralytics")


class SegmentationProcessor:
    """
    Segmentación de instancias sobre frames BGR. `segment()` es bloqueante:
    llamarlo siempre desde el worker de VisionPipeline.
    """

    def __init__(self):
        self._model          = None
        self._model_path: Optional[str] = None
        self.enabled         = False
        self.confidence      = 0.35
        self.imgsz           = 416      # la máscara no necesita resolución alta
        self.focus_mode      = "mask"   # "mask" | "overlay"
        self.mask_margin_px  = 15       # dilatación: margen alrededor de los objetos
        self._inf_ms         = 0.0
        self._inf_fps        = 0.0
        self._region_count   = 0
        self._last_contours: list = []

    # ── API pública ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return ULTRALYTICS_AVAILABLE

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load_model(self, model_name: str = "yolov8n-seg.pt") -> bool:
        """
        Carga el modelo de segmentación (busca en models/, luego descarga)
        y hace warm-up. Bloqueante — llamar desde run_in_executor.
        """
        if not ULTRALYTICS_AVAILABLE:
            log.error("[SEG] ultralytics no instalado")
            return False

        local = MODELS_DIR / model_name
        path  = str(local) if local.exists() else model_name

        try:
            log.info(f"[SEG] Cargando modelo: {path}")
            model = YOLO(path)
            dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
            model(dummy, imgsz=self.imgsz, verbose=False)
            self._model      = model
            self._model_path = model_name
            log.info(f"[SEG] Modelo {model_name} listo (imgsz={self.imgsz})")
            return True
        except Exception as e:
            log.error(f"[SEG] Error cargando {model_name}: {e}")
            self._model = None
            return False

    def segment(self, frame_bgr: np.ndarray) -> Optional[np.ndarray]:
        """
        Inferencia síncrona. Devuelve la máscara binaria uint8 (255 = objeto)
        del tamaño del frame, dilatada `mask_margin_px`, o None si el modelo
        no detectó ninguna región. Actualiza contornos para el overlay.
        """
        if self._model is None:
            return None

        t0 = time.perf_counter()
        results = self._model(frame_bgr, conf=self.confidence,
                              imgsz=self.imgsz, verbose=False)
        dt = time.perf_counter() - t0
        self._inf_ms  = round(dt * 1000, 1)
        self._inf_fps = round(1.0 / dt, 1) if dt > 0 else 0.0

        r = results[0]
        if r.masks is None or len(r.masks.data) == 0:
            self._region_count  = 0
            self._last_contours = []
            return None

        # Unión de todas las máscaras de instancia (resolución del modelo)
        masks    = r.masks.data.cpu().numpy()            # (N, h, w) float
        combined = (masks.max(axis=0) > 0.5).astype(np.uint8) * 255

        h, w = frame_bgr.shape[:2]
        mask = cv2.resize(combined, (w, h), interpolation=cv2.INTER_NEAREST)

        if self.mask_margin_px > 0:
            k = self.mask_margin_px * 2 + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            mask = cv2.dilate(mask, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        self._region_count  = len(masks)
        self._last_contours = list(contours)
        return mask

    @staticmethod
    def apply_focus(frame_bgr: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
        """Suprime el fondo: deja solo los píxeles dentro de la máscara."""
        if mask is None:
            return frame_bgr
        return cv2.bitwise_and(frame_bgr, frame_bgr, mask=mask)

    @property
    def status(self) -> dict:
        return {
            "available":     ULTRALYTICS_AVAILABLE,
            "model_loaded":  self._model is not None,
            "model_path":    self._model_path,
            "enabled":       self.enabled,
            "confidence":    self.confidence,
            "imgsz":         self.imgsz,
            "focus_mode":    self.focus_mode,
            "inf_ms":        self._inf_ms,
            "inf_fps":       self._inf_fps,
            "region_count":  self._region_count,
        }

    @staticmethod
    def list_local_models() -> list:
        """Modelos de segmentación en models/ (convención: contienen "-seg")."""
        exts = ("*.pt", "*.onnx", "*.engine")
        names = []
        for ext in exts:
            names.extend(f.name for f in MODELS_DIR.glob(ext))
        return sorted(n for n in set(names) if "-seg" in n)
