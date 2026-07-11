# Guía de fine-tuning YOLO — Mobula8-Autopilot

Cómo entrenar un modelo YOLO propio sobre las grabaciones del drone y cómo
**reducir su tamaño y latencia de inferencia** para que el pipeline de visión
(`docs/VISION_PIPELINE.md`) corra más rápido en el laptop (y, en Fase 4, en
un Jetson u otro sistema embebido).

Última actualización: 2026-07-11 (v2.6.0).

---

## 0. Objetivo y criterio de éxito

Los modelos COCO genéricos (`yolov8n.pt`) detectan 80 clases que no
necesitamos y a una resolución (640 px) que el video NTSC de la EasyCap no
aprovecha. Un modelo fine-tuneado a **nuestras clases y nuestro dominio**
(imagen analógica con ruido, tinte magenta, desenfoque de movimiento) es a
la vez **más preciso y más rápido**.

Referencia medida en este proyecto (laptop CPU, frame 1280×720):

| Configuración | Latencia por frame |
|---------------|--------------------|
| yolov8n @ imgsz 640 | ~120–150 ms |
| yolov8n @ imgsz 416 | ~50–80 ms |
| yolov8n-seg @ imgsz 416 (etapa de segmentación) | ~55–90 ms |
| Cascada seg(416) + det(640) | ~135–175 ms |

Criterio de éxito de un fine-tuning:

- **Latencia**: detector ≤ 60 ms/frame en CPU (≥ 15 FPS de visión), medido
  en `GET /api/vision/status → latency.pipeline_ms` con el stream real.
- **Precisión**: mAP50 sobre el set de validación propio ≥ el del modelo
  base evaluado en ese mismo set (normalmente lo supera con holgura al
  reducir clases).
- **Tamaño**: ≤ 7 MB (`.pt` de yolov8n) o ≤ 13 MB (`.onnx`); relevante para
  el deploy embebido de Fase 4.

## 1. Entorno

El mismo entorno del proyecto sirve para entrenar:

```bash
pip install -r requirements-yolo.txt        # ultralytics (trae torch CPU)
```

Entrenar en CPU es viable para datasets pequeños (<1000 imágenes, yolov8n,
~1–3 h) pero lento. Si hay GPU NVIDIA disponible, instalar torch CUDA
**antes** (ver `docs/SETUP.md`); también se puede entrenar gratis en Google
Colab (GPU T4) y traer el `best.pt` de vuelta.

Para los pasos de optimización (sección 6) hacen falta extras opcionales:

```bash
pip install onnx onnxruntime      # export/inferencia ONNX
pip install openvino              # cuantización INT8 para CPU Intel
```

## 2. Construir el dataset desde las grabaciones propias

La mejor fuente de datos es el propio sistema: las grabaciones MP4 quedan en
`logs/video/` sincronizadas con cada sesión.

1. **Volar y grabar** en las condiciones reales de uso: interiores y
   exteriores, distintas luces, con el ruido analógico típico. La corrección
   de imagen (WB/gamma) del streamer **sí** se aplica a la grabación en vivo,
   así que los frames grabados se parecen a lo que verá el modelo.
2. **Extraer frames** a 1–2 fps (más densidad solo genera casi-duplicados):

   ```bash
   # ffmpeg (recomendado)
   ffmpeg -i logs/video/video_20260711_120000.mp4 -vf fps=2 dataset/raw/f_%05d.jpg

   # o con OpenCV si no hay ffmpeg
   python - <<'EOF'
   import cv2, pathlib
   cap = cv2.VideoCapture("logs/video/video_20260711_120000.mp4")
   fps = cap.get(cv2.CAP_PROP_FPS) or 30
   step = int(fps // 2); n = i = 0
   out = pathlib.Path("dataset/raw"); out.mkdir(parents=True, exist_ok=True)
   while True:
       ok, frame = cap.read()
       if not ok: break
       if i % step == 0:
           cv2.imwrite(str(out / f"f_{n:05d}.jpg"), frame); n += 1
       i += 1
   print(n, "frames")
   EOF
   ```

3. **Curar**: eliminar frames estáticos repetidos y los completamente
   corruptos por pérdida de señal (pero **conservar** algunos con ruido
   moderado — es el dominio real). Apuntar a **300–1000 imágenes por clase**,
   incluyendo ~10 % de **negativos** (frames sin ningún objeto) para bajar
   falsos positivos.

## 3. Etiquetado

Herramientas que exportan directamente en formato YOLO:

- **Roboflow** (web, gratuito hasta cierto volumen; su "Auto Label" y
  SAM-assist aceleran mucho, y genera el `data.yaml` solo).
- **CVAT** o **Label Studio** (self-hosted, sin subir video a terceros).

Formato YOLO: un `.txt` por imagen con `class x_center y_center w h`
normalizados 0–1. Estructura estándar:

```
dataset/
├── data.yaml
├── images/{train,val,test}/
└── labels/{train,val,test}/
```

`data.yaml`:

```yaml
path: ./dataset
train: images/train
val: images/val
test: images/test
names:
  0: persona
  1: puerta
  2: obstaculo
```

Split típico 80/10/10. Regla de oro: **frames del mismo vuelo no deben
repartirse entre train y val** (son casi idénticos e inflan las métricas);
separar por sesión de vuelo.

Si además se va a fine-tunear la **etapa de segmentación**, etiquetar
máscaras (polígonos) en vez de cajas — Roboflow/CVAT lo soportan con ayuda
de SAM — y usar el mismo flujo con `yolov8n-seg.pt` como base.

## 4. Fine-tuning (detección)

Partir **siempre de yolov8n** (transfer learning), nunca entrenar de cero:

```bash
yolo detect train \
    model=yolov8n.pt \
    data=dataset/data.yaml \
    epochs=100 patience=20 \
    imgsz=416 batch=16 \
    project=runs name=mobula_v1
```

Notas:

- **`imgsz=416`**: entrenar ya a la resolución de inferencia objetivo. El
  video NTSC digitalizado no tiene detalle real que justifique 640, y esta
  sola decisión reduce la latencia ~2× (ver tabla de la sección 0).
- **`patience=20`**: early stopping; con datasets pequeños el óptimo suele
  llegar antes de 60 épocas.
- **Dataset pequeño (<500 imágenes)**: añadir `freeze=10` (congela el
  backbone, entrena solo la cabeza) — entrena más rápido y sobreajusta menos.
- **Una sola clase**: añadir `single_cls=True` si solo importa un tipo de
  objeto; simplifica la cabeza y el NMS.
- Las **augmentations** por defecto de ultralytics (mosaic, HSV, flip) van
  bien para este dominio; no tocarlas en la primera iteración.

El resultado queda en `runs/mobula_v1/weights/best.pt`.

Para la etapa de segmentación es igual con `yolo segment train
model=yolov8n-seg.pt ...` y labels de polígonos.

## 5. Validar antes de optimizar

```bash
yolo val model=runs/mobula_v1/weights/best.pt data=dataset/data.yaml imgsz=416
```

Anotar `mAP50` y `mAP50-95`: son la línea base contra la que se compara
cada paso de optimización de la sección 6 (la cuantización, p. ej., puede
costar 1–3 puntos de mAP; hay que saberlo antes de volar con ese modelo).

## 6. Reducir tamaño y latencia

En orden de costo/beneficio — aplicar de arriba hacia abajo y medir en cada
paso:

### 6.1 Elegir el modelo más pequeño (gratis)

En CPU, `yolov8n` es la única opción sensata para tiempo real; `s` solo si
la GPU está disponible; `m` queda para post-proceso offline de grabaciones.
Un fine-tuning con pocas clases recupera con creces la precisión que se
pierde por usar `n`.

### 6.2 Reducir la resolución de inferencia (gratis)

`imgsz` 640 → 416 ≈ latencia ÷2; 416 → 320 ≈ otro ~35 % menos, con pérdida
visible en objetos lejanos/pequeños. Configurable en runtime sin reentrenar:

```bash
curl -X POST localhost:8080/api/yolo/config \
     -H "Content-Type: application/json" \
     -d '{"enabled": true, "model": "mobula_v1.pt", "confidence": 0.5, "imgsz": 416}'
```

Idealmente coincide con el `imgsz` de entrenamiento (sección 4).

### 6.3 Exportar a ONNX (CPU genérica, ~1.3–1.8× más rápido)

```bash
yolo export model=runs/mobula_v1/weights/best.pt format=onnx imgsz=416 simplify=True
```

Copiar el `.onnx` a `models/` — el backend lo carga igual que un `.pt`
(ultralytics usa onnxruntime por debajo; requiere `pip install onnxruntime`).

### 6.4 Cuantización INT8 (CPU Intel: OpenVINO, ~2–3× adicional)

```bash
yolo export model=runs/mobula_v1/weights/best.pt format=openvino int8=True \
     data=dataset/data.yaml imgsz=416
```

`int8=True` necesita el `data.yaml` para calibrar. Produce una carpeta
`*_openvino_model/`; colocarla dentro de `models/` y seleccionarla por
nombre de carpeta. Verificar el mAP tras cuantizar (paso 5): si cae >3
puntos, probar calibración con más imágenes.

### 6.5 TensorRT (solo Fase 4, Jetson/GPU NVIDIA)

```bash
yolo export model=best.pt format=engine half=True imgsz=416   # FP16
```

Los `.engine` son específicos del hardware donde se exportan — generar en
el Jetson, no en el laptop.

### 6.6 Pruning y distilación (último recurso)

Recortar canales del backbone o destilar a una arquitectura menor puede dar
otro 20–40 %, pero exige reentrenar y tooling extra (p. ej.
`torch-pruning`). Con 6.1–6.4 aplicados, el cuello de botella del sistema
pasa a ser la captura EasyCap, no el modelo — no suele valer la pena.

### Expectativa acumulada (yolov8n, CPU laptop, 1 worker)

| Paso | Latencia estimada | Tamaño |
|------|-------------------|--------|
| base `.pt` @ 640 | ~120–150 ms | 6.2 MB |
| @ 416 | ~50–80 ms | 6.2 MB |
| + ONNX | ~35–60 ms | ~12 MB |
| + OpenVINO INT8 | ~20–40 ms | ~3.5 MB |

## 7. Benchmark y medición en el sistema real

Micro-benchmark de ultralytics (compara formatos de golpe):

```bash
yolo benchmark model=runs/mobula_v1/weights/best.pt imgsz=416 data=dataset/data.yaml
```

Medición **en el pipeline real** (la que cuenta): arrancar el stream,
activar las etapas en el panel AI y leer `GET /api/vision/status`:

- `detection.inf_ms` / `segmentation.inf_ms` — latencia por etapa
- `latency.pipeline_ms` — cascada completa por frame
- `latency.vision_fps` — throughput real de visión
- `governor.max_speed_ms` — velocidad máxima que esa latencia permite
  (ver `docs/VISION_PIPELINE.md`)

## 8. Desplegar en el sistema

1. Copiar el modelo a `models/` en la raíz del repo. Convención de nombres:
   los modelos de **segmentación deben contener `-seg`** en el nombre
   (`mobula-seg_v1.pt`); el resto se listan como detección.
2. Aparece automáticamente en el panel AI de la UI (`/api/vision/models`).
3. Seleccionarlo, ajustar confidence y activar. Verificar FPS/latencia en
   el HUD del stream y contra el criterio de éxito de la sección 0.
4. Guardar junto al modelo un `.md` con: dataset usado (sesiones), fecha,
   mAP de validación y latencia medida — imprescindible para comparar
   iteraciones.
