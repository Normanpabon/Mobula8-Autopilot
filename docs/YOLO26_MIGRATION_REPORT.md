# Informe de migración a YOLO26

Fecha: 2026-09-22. Alcance: implementación del plan suministrado, adaptada al
worker y ROI existentes. Cambios preparados en el árbol de trabajo, sin commit.

## Resultado

Implementada la migración de software. Pendiente la aceptación con datos de
campo y hardware de vuelo. No se declara cumplida la equivalencia de calidad
respecto a la cascada antigua ni una mejora general de latencia.

- `VisionModel`: YOLO26n detect y YOLO26n-seg segment, salida `Detection` con
  clase, score, caja y máscara opcional. Una llamada por frame; la segmentación
  proporciona también las cajas. Eliminados los dos procesadores antiguos.
- Configuración JSON validada y persistente: modo, modelos, imgsz por tarea,
  clases resueltas desde `model.names`, thresholds por clase, overlay, presets
  analógico/digital y ventana de métricas. Soporta vocabulario de fine-tuning.
- Cambios transaccionales de modelo: serialización con inferencia, warm-up,
  descarte de resultados anteriores y conservación del estado ante errores.
- API `/api/vision/config` y estado ampliado con modo, modelo, clases,
  confidence, latencias, edad, FPS y p50/p95. Rutas antiguas seleccionan modos
  excluyentes y devuelven el nuevo esquema unificado.
- Panel AI con selector OFF / DETECT / SEGMENT y edición de configuración;
  indica fallos y muestra estado efectivo desde el servidor.
- Conservados ROI, worker separado de WebRTC, grabación limpia y la política
  `stale → HOVER`. La visión sigue sin enviar comandos RC.
- Ultralytics fijado a 8.4.0, manifest de modelos y workflow de CI con tests y
  smoke de pesos reales. CI queda preparado, no se ha ejecutado remotamente.
- Benchmark de seis variantes, SHA256 de fuente y baseline histórico documentado.

## Validación realizada

Entorno de pruebas temporal: Python 3.14.7, Ultralytics 8.4.0 y PyTorch
2.14.0+cpu. No se modificó un entorno de producción. La instalación inicial
intentó incluir CUDA y falló por espacio; se completó con PyTorch CPU.

- Suite completa Python: **56 tests OK** en la última ejecución completa.
- Se añadieron después dos regresiones de concurrencia/métricas; suite de
  visión final: **20 tests OK**, incluidas esas dos (58 tests Python disponibles).
- JavaScript: **4 suites OK**, incluida configuración del panel AI y manejo
  de errores, además de vídeo, ROI y controles seriales.
- Compilación Python y `git diff --check`: OK.
- Pesos reales: YOLO26n y YOLO26n-seg cargaron, hicieron warm-up y produjeron
  cajas no vacías; segment produjo máscaras no vacías sobre `bus.jpg`.
- Pruebas de ROI y API, clases inexistentes, thresholds, lista vacía, exclusión
  de clases, tareas incompatibles, DETECT→SEGMENT→DETECT→OFF, liberación de
  referencias y fallos de persistencia/carga: OK.
- Prueba de cambio durante inferencia: el overlay no espera al worker y el
  resultado anterior no puede publicarse tras cambiar de modelo.

## Medición técnica, no aceptación de campo

`benchmarks/smoke_cpu.json`: 20 frames estáticos del asset `bus.jpg`, a 480×640,
misma fuente y configuración para las seis variantes. Es un smoke reproducible,
no un clip FPV ni una medición de precisión. Otra prueba de pesos pudo coincidir
al inicio; repetir sin cargas concurrentes antes de extraer conclusiones de
rendimiento. Valores de inferencia observados en ms:

| Modelo | imgsz | p50 | p95 |
|---|---:|---:|---:|
| YOLOv8n | 640 | 49.4 | 71.8 |
| YOLOv8n | 416 | 24.6 | 38.2 |
| YOLO26n | 640 | 53.7 | 65.4 |
| YOLO26n | 416 | 25.8 | 30.2 |
| YOLO26n-seg | 416 | 38.1 | 41.0 |
| YOLO26n-seg | 640 | 72.1 | 79.7 |

Esta muestra no demuestra menor mediana de YOLO26n frente a YOLOv8n. La
eliminación de la segunda inferencia está demostrada por tests y arquitectura;
su impacto en vuelo necesita una evaluación independiente. FP/FN, GPU/VRAM y
edad de resultado en reproducción offline se registran como null cuando no
se miden. Los números históricos del plan se conservan separados.

## Pendientes y siguiente ciclo

1. **Congelar datos de validación**: capturar clips analógico y digital con
   personas, vehículos, animales y objetos pequeños. Anotar cajas/máscaras.
   La grabación actual de logs tiene 258 bytes y no contiene frames utilizables.
2. **Medir en banco en el equipo objetivo**: ejecutar la matriz sobre ambos
   clips, registrar p95 y recall/precision/mAP, FP/FN y consumo. Medir también
   WebRTC y grabación simultáneos. Los tests actuales evitan regresiones de
   software, pero no certifican ausencia de degradación en hardware real.
3. **Puerta de aceptación**: comprobar calidad equivalente o superior, menor
   pipeline/p95 y máscaras útiles. Ajustar 416/512/640 según objetos pequeños.
   Si falla, usar OFF o seleccionar pesos anteriores de la misma tarea desde
   configuración; la cascada antigua solo existe en el historial Git.
4. **Fine-tuning agrícola**: definir dataset y clases (tractor, cultivos,
   maleza, etc.), separar entrenamiento/validación/test y comparar contra
   COCO. La guía YOLO26_FINETUNING_GUIDE.md mencionada en el plan no fue adjuntada.
5. **Optimización posterior**: evaluar ONNX/OpenVINO/TensorRT y cuantización
   únicamente después de establecer el baseline del equipo objetivo. La
   integración de visión con el autopilot requiere su propio ciclo de seguridad.

## Mensaje de commit propuesto

```text
feat(vision): migrate to YOLO26 with single-pass detection and segmentation

- replace SEG→DET cascade with exclusive off/detect/segment modes
- add validated persistent config, class thresholds and camera presets
- preserve ROI, async worker, clean recording and stale-to-hover governor
- expose vision config and metrics through API and unified AI panel
- pin Ultralytics 8.4.0 and add real-model smoke, regressions and benchmark
- document technical results and pending field acceptance
```

Referencias: [YOLO26 oficial](https://docs.ultralytics.com/models/yolo26/),
[segmentación Ultralytics](https://docs.ultralytics.com/tasks/segment/).
