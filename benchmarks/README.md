# Comparación reproducible de visión

Instalar `requirements-yolo.txt` (Ultralytics 8.4.0). Para CPU instalar primero
PyTorch/torchvision desde `https://download.pytorch.org/whl/cpu`.

```bash
python scripts/benchmark_vision.py benchmarks/analog_reference.mp4 --frames 300 --output benchmarks/analog_results.json
python scripts/benchmark_vision.py benchmarks/digital_reference.mp4 --frames 300 --output benchmarks/digital_results.json
```

Cada ejecución recorre los mismos primeros N frames del clip en seis variantes:
YOLOv8n 640/416, YOLO26n 640/416 y YOLO26n-seg 416/640. Guarda SHA256 del clip,
versiones, configuración, carga, warm-up, inferencia y pipeline p50/p95, FPS,
CPU del proceso y pico de RAM. Incluye ROI completa y normalización. Excluye
la latencia de transporte de captura/WebRTC; `result_age_ms` offline es null.
CPU puede exceder 100% por uso de varios cores. GPU/VRAM no instrumentadas:
son null, nunca cero inventado. Usar la API en vivo para edad y governor.

`smoke_cpu.json` es exclusivamente una prueba técnica sobre 20 frames estáticos
de `bus.jpg`, incluido con Ultralytics. No representa vuelo, cámara analógica,
recall, precision o rendimiento sostenible. Se reproduce así:

```bash
python scripts/create_smoke_clip.py /tmp/mobula-yolo-smoke.avi
python scripts/benchmark_vision.py /tmp/mobula-yolo-smoke.avi --frames 20 --output benchmarks/smoke_cpu.json
```

Baseline histórico aportado por el plan, **no medido en esta migración**:

| Pipeline | Latencia histórica |
|---|---:|
| YOLOv8n 640 | 120–150 ms |
| YOLOv8n 416 | 50–80 ms |
| YOLOv8n-seg 416 | 55–90 ms |
| SEG 416 + DET 640 | 135–175 ms |

Falta congelar clips analógico y digital representativos y sus anotaciones.
La grabación encontrada en logs tiene 258 bytes y no ofrece frames decodificables.
No hay `yolov8_baseline.json` de campo porque aún no existe una medición válida.
Antes de aceptar rendimiento: medir ambos clips en el hardware objetivo, al
menos 300 frames/modelo, sin otros trabajos pesados; revisar p95, FP/FN y objetos
pequeños. Calcular precision, recall y mAP con un dataset anotado de validación
(`model.val(data=..., imgsz=...)`), comparable entre modelos de la misma tarea.
Un dataset de segmentación necesita máscaras; no inferir métricas de accuracy
partiendo de un vídeo sin etiquetas. No se declara alcanzado el criterio de
calidad del plan hasta completar esta evaluación.
