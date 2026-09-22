"""
VisionPipeline — Cascada de visión por computadora sobre el video FPV
=====================================================================
Orquesta las dos etapas de visión y su impacto en el vuelo:

    captura → [segmentación] → [detección YOLO] → overlay + LatencyGovernor

Diseño (v2.6.0, ver docs/VISION_PIPELINE.md):

- **Inferencia desacoplada del stream**: un loop propio toma el último frame
  disponible, corre las etapas habilitadas en un ThreadPoolExecutor de
  1 worker y publica el resultado (detecciones, contornos, latencias).
  El track WebRTC nunca espera a la inferencia: `annotate()` solo dibuja el
  último resultado publicado sobre el frame actual (<1 ms de cv2). El video
  mantiene sus FPS aunque la visión corra a 2–5 FPS.
- **Etapas independientes**: `segmenter.enabled` y `detector.enabled` se
  encienden/apagan por separado. Con ambas encendidas y focus_mode="mask",
  la máscara de segmentación suprime el fondo antes del detector.
- **LatencyGovernor**: traduce la latencia medida del pipeline en una
  velocidad máxima recomendada para el futuro autopilot (Fase 4). Más
  etapas encendidas → más latencia → menor velocidad recomendada.
"""

import asyncio
import concurrent.futures
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import cv2

from yolo_processor import YOLOProcessor
from segmentation_processor import SegmentationProcessor
from vision_roi import RegionSelection, CONFIG_FILE as ROI_CONFIG_FILE

log = logging.getLogger("vision_pipeline")


@dataclass
class VisionResult:
    """Resultado de una pasada completa del pipeline sobre un frame."""
    detections:   list  = field(default_factory=list)
    contours:     list  = field(default_factory=list)
    region_count: int   = 0
    seg_ms:       float = 0.0
    det_ms:       float = 0.0
    pipeline_ms:  float = 0.0
    seg_used:     bool  = False
    det_used:     bool  = False
    roi_revision: int = 0
    frame_shape: tuple = ()
    ts:           float = 0.0   # time.time() al terminar la pasada


class LatencyGovernor:
    """
    Política de compensación de latencia para vuelo asistido por visión.

    El autopilot (Fase 4) no debe volar más rápido de lo que ve: si un
    obstáculo aparece a `safety_distance_m`, el sistema necesita percibirlo
    (captura + pipeline + edad del resultado) y reaccionar (decisión +
    inyección CRSF + uplink ELRS + dinámica del drone) antes de recorrer
    esa distancia. De ahí:

        v_max = safety_distance_m / (t_captura + t_pipeline + t_edad + t_reacción)

    Modos que expone `evaluate()`:
    - "off":        visión apagada — el autopilot volaría solo con límites
                    de telemetría (la visión no gobierna).
    - "warming_up": etapas encendidas pero sin resultados aún → no volar.
    - "active":     resultados frescos → v_max calculado.
    - "stale":      el último resultado supera `stale_after_ms` (inferencia
                    colgada o demasiado lenta) → recomendar hover (v_max 0).
    """

    CAPTURE_BASE_MS = 75.0   # digitalización EasyCap (~50–100 ms, ver ARCHITECTURE.md)

    def __init__(self):
        self.safety_distance_m  = 3.0
        self.reaction_time_ms   = 250.0  # decisión + inyección CRSF + uplink + respuesta del drone
        self.stale_after_ms     = 1500.0
        self.max_speed_cap_ms   = 8.0    # techo físico aproximado del Mobula8
        self.min_speed_floor_ms = 0.3    # por debajo de esto, mejor hover

    def evaluate(self, result: Optional[VisionResult], vision_active: bool) -> dict:
        base = {
            "safety_distance_m": self.safety_distance_m,
            "reaction_time_ms":  self.reaction_time_ms,
            "capture_base_ms":   self.CAPTURE_BASE_MS,
            "stale_after_ms":    self.stale_after_ms,
        }
        if not vision_active:
            return {**base, "mode": "off", "max_speed_ms": None,
                    "total_latency_ms": None, "result_age_ms": None,
                    "recommendation": "Visión apagada — límites por telemetría solamente"}
        if result is None:
            return {**base, "mode": "warming_up", "max_speed_ms": 0.0,
                    "total_latency_ms": None, "result_age_ms": None,
                    "recommendation": "Sin resultados de visión aún — no volar"}

        age_ms = (time.time() - result.ts) * 1000.0
        if age_ms > self.stale_after_ms:
            return {**base, "mode": "stale", "max_speed_ms": 0.0,
                    "total_latency_ms": None, "result_age_ms": round(age_ms, 1),
                    "recommendation": "Resultados viejos — hover hasta recuperar visión"}

        total_ms = (self.CAPTURE_BASE_MS + result.pipeline_ms
                    + age_ms + self.reaction_time_ms)
        v_max = self.safety_distance_m / (total_ms / 1000.0)
        v_max = max(self.min_speed_floor_ms, min(self.max_speed_cap_ms, v_max))
        return {**base, "mode": "active",
                "total_latency_ms": round(total_ms, 1),
                "result_age_ms":    round(age_ms, 1),
                "max_speed_ms":     round(v_max, 2),
                "recommendation":   f"Velocidad máxima recomendada: {v_max:.2f} m/s"}


class VisionPipeline:
    """
    Fachada de visión: procesadores, loop de inferencia, overlay y governor.
    `start()`/`stop()` siguen el ciclo de vida de la captura de video.
    """

    # No dibujar resultados más viejos que esto (engañarían al piloto)
    OVERLAY_MAX_AGE_S = 2.0

    def __init__(self, roi_path=ROI_CONFIG_FILE):
        self._roi_path = roi_path
        try:
            self._roi = RegionSelection.load(roi_path)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            log.error("ROI inválida: %s; inferencia pausada", exc)
            self._roi = RegionSelection((False,) * 96)
        self._roi_revision = 0
        self._roi_state = (self._roi, self._roi_revision)
        self.detector  = YOLOProcessor()
        self.segmenter = SegmentationProcessor()
        self.governor  = LatencyGovernor()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vision")
        self._task:   Optional[asyncio.Task] = None
        self._running = False
        self._frame_getter = None
        self._latest: Optional[VisionResult] = None
        self._vision_fps = 0.0

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self.detector.is_available()

    @property
    def active(self) -> bool:
        """True si al menos una etapa está encendida y con modelo cargado."""
        return any(self._roi.cells) and ((self.segmenter.enabled and self.segmenter.is_loaded)
                or (self.detector.enabled and self.detector.is_loaded))

    @property
    def roi_status(self):
        return {**self._roi.status, 'revision': self._roi_revision}

    def set_roi(self, cells):
        selection = RegionSelection(tuple(cells))
        selection.save(self._roi_path)
        self._roi = selection
        self._roi_revision += 1
        self._roi_state = (self._roi, self._roi_revision)
        self._latest = None
        self._vision_fps = 0.0
        return self.roi_status

    def _publish(self, result):
        if result.roi_revision == self._roi_revision:
            self._latest = result

    def start(self, frame_getter) -> None:
        """Arranca el loop de inferencia. `frame_getter`: async → BGR o None."""
        self._frame_getter = frame_getter
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            log.info("[Vision] Loop de inferencia iniciado")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._latest = None
        log.info("[Vision] Loop de inferencia detenido")

    # ── Loop de inferencia (desacoplado del stream) ──────────────────────────

    async def _run_loop(self):
        loop = asyncio.get_event_loop()
        while self._running:
            if not self.active or self._frame_getter is None:
                await asyncio.sleep(0.2)
                continue
            frame = await self._frame_getter()
            if frame is None:
                await asyncio.sleep(0.1)
                continue
            try:
                t0 = time.perf_counter()
                result = await loop.run_in_executor(
                    self._executor, self._process, frame)
                dt = time.perf_counter() - t0
                self._vision_fps = round(1.0 / dt, 1) if dt > 0 else 0.0
                self._publish(result)
            except Exception as e:
                log.error(f"[Vision] Error en pipeline: {e}")
                await asyncio.sleep(0.5)
            # Ceder el control; el executor de 1 worker ya limita el ritmo
            await asyncio.sleep(0)

    def _process(self, frame_bgr: np.ndarray) -> VisionResult:
        """Cascada síncrona: [segmentación] → [detección]. Corre en el worker."""
        t0 = time.perf_counter()
        seg_used = self.segmenter.enabled and self.segmenter.is_loaded
        det_used = self.detector.enabled and self.detector.is_loaded

        selection, revision = self._roi_state
        full_mask = selection.mask(*frame_bgr.shape[:2])
        ys, xs = np.flatnonzero(full_mask.any(axis=1)), np.flatnonzero(full_mask.any(axis=0))
        if not len(xs):
            return VisionResult(roi_revision=revision, frame_shape=frame_bgr.shape[:2], ts=time.time())
        x0, xend, y0, yend = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
        roi_mask = full_mask[y0:yend, x0:xend]
        # Crop the envelope for useful model resolution, mask holes/propellers.
        cropped = cv2.bitwise_and(frame_bgr[y0:yend, x0:xend],
                                 frame_bgr[y0:yend, x0:xend], mask=roi_mask)
        work = cropped
        contours = []
        seg_ms = det_ms = 0.0
        detections = []
        if seg_used:
            mask = self.segmenter.segment(cropped)
            seg_ms = self.segmenter._inf_ms
            if mask is not None:
                # Clip even the segmenter's dilation to the user's selection.
                mask = cv2.bitwise_and(mask, roi_mask)
                local_contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                offset = np.array([[[x0, y0]]], dtype=np.int32)
                contours = [contour + offset for contour in local_contours]
            if det_used and self.segmenter.focus_mode == "mask":
                work = SegmentationProcessor.apply_focus(cropped, mask)

        if det_used:
            raw_detections = self.detector.infer(work)
            det_ms = self.detector._inf_ms
            h, w = roi_mask.shape
            for detection in raw_detections:
                box = np.asarray(detection['bbox'], dtype=float)
                if box.shape != (4,) or not np.isfinite(box).all():
                    continue
                x1, y1, x2, y2 = np.clip(box, [0, 0, 0, 0], [w, h, w, h])
                if x2 <= x1 or y2 <= y1:
                    continue
                cx, cy = min(w - 1, int((x1 + x2) / 2)), min(h - 1, int((y1 + y2) / 2))
                area = roi_mask[int(y1):int(np.ceil(y2)), int(x1):int(np.ceil(x2))]
                if not roi_mask[cy, cx] or np.count_nonzero(area) < area.size / 2:
                    continue
                detections.append({**detection, 'bbox': [float(x1 + x0), float(y1 + y0),
                                                        float(x2 + x0), float(y2 + y0)]})

        return VisionResult(
            detections=detections, contours=contours, region_count=len(contours),
            seg_ms=seg_ms, det_ms=det_ms,
            pipeline_ms=round((time.perf_counter() - t0) * 1000, 1),
            seg_used=seg_used, det_used=det_used, ts=time.time(),
            roi_revision=revision, frame_shape=frame_bgr.shape[:2],
        )

    # ── Overlay (camino del stream — debe ser barato) ────────────────────────

    def annotate(self, frame_bgr: np.ndarray) -> np.ndarray:
        """
        Dibuja el último resultado publicado sobre el frame actual.
        Solo primitivas cv2 (<1 ms) — apto para llamarse por cada frame
        del stream sin afectar los FPS del video. Muta el frame recibido
        (que ya es una copia del buffer de captura).
        """
        if not self.active:
            return frame_bgr
        r = self._latest
        if r is None or r.roi_revision != self._roi_revision or r.frame_shape != frame_bgr.shape[:2]:
            return frame_bgr

        original = frame_bgr.copy() if not all(self._roi.cells) else None
        age = time.time() - r.ts
        if age <= self.OVERLAY_MAX_AGE_S:
            if r.contours:
                cv2.drawContours(frame_bgr, r.contours, -1, (0, 255, 255), 2)
            for d in r.detections:
                x1, y1, x2, y2 = (int(v) for v in d["bbox"])
                cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (136, 255, 0), 2)
                label = f"{d['class']} {d['confidence']:.2f}"
                cv2.putText(frame_bgr, label, (x1, max(y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (136, 255, 0), 1,
                            cv2.LINE_AA)

        if original is not None:
            excluded = self._roi.mask(*frame_bgr.shape[:2]) == 0
            frame_bgr[excluded] = original[excluded]

        # HUD de latencia + governor (abajo a la izquierda)
        gov = self.governor.evaluate(r, True)
        parts = []
        if r.seg_used:
            parts.append(f"seg {r.seg_ms:.0f}ms")
        if r.det_used:
            parts.append(f"det {r.det_ms:.0f}ms")
        hud = f"VISION {r.pipeline_ms:.0f}ms ({' + '.join(parts)}) @ {self._vision_fps:.1f}fps"
        if gov["mode"] == "active":
            hud += f" | Vmax {gov['max_speed_ms']:.1f} m/s"
        elif gov["mode"] == "stale":
            hud += " | STALE - HOVER"
        h = frame_bgr.shape[0]
        cv2.putText(frame_bgr, hud, (10, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 229, 255), 1, cv2.LINE_AA)
        return frame_bgr

    # ── Estado ───────────────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        r = self._latest
        age_ms = round((time.time() - r.ts) * 1000, 1) if r else None
        return {
            "available":    self.is_available(),
            "running":      self._running,
            "active":       self.active,
            "roi": self.roi_status,
            "detection": {**self.detector.status,
                          "detections": r.detections if r else [],
                          "detection_count": len(r.detections) if r else 0},
            "segmentation": {**self.segmenter.status, "region_count": r.region_count if r else 0},
            "latency": {
                "seg_ms":         r.seg_ms if r else 0.0,
                "det_ms":         r.det_ms if r else 0.0,
                "pipeline_ms":    r.pipeline_ms if r else 0.0,
                "result_age_ms":  age_ms,
                "vision_fps":     self._vision_fps,
            },
            "governor": self.governor.evaluate(r, self.active),
        }
