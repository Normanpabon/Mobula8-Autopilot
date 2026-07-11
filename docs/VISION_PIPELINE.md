# Pipeline de visión y política de latencia — Mobula8-Autopilot

Diseño del flujo de procesamiento de video con visión por computadora
(v2.6.0): cascada segmentación → detección YOLO, etapas conmutables, y cómo
la latencia que introducen gobernará el comportamiento del futuro piloto
automático (Fase 4).

Última actualización: 2026-07-11 (v2.6.0).

---

## 1. Flujo de procesamiento

```
                 VideoCapture (OpenCV, loop propio)
                        │  frames BGR corregidos (WB/gamma)
                        ▼
        ┌─────────── último frame ────────────┐
        │                                     │
        ▼ (cada frame, <1 ms)                 ▼ (al ritmo que pueda, 2–15 FPS)
  VisionPipeline.annotate()            VisionPipeline._run_loop()
  dibuja el ÚLTIMO resultado           ThreadPoolExecutor (1 worker):
  publicado (cajas, contornos,           [segmentación]  seg.enabled
  HUD de latencia y Vmax)                     │ máscara (focus_mode="mask":
        │                                     ▼  suprime el fondo)
        ▼                                [detección YOLO] det.enabled
  FPVVideoTrack → WebRTC                      │
                                              ▼
                                       VisionResult {detecciones, contornos,
                                       latencias por etapa, timestamp}
                                              │
                                              ▼
                                       LatencyGovernor → Vmax recomendada
```

Módulos: `backend/vision_pipeline.py` (orquestador + governor),
`backend/segmentation_processor.py` (etapa 1), `backend/yolo_processor.py`
(etapa 2). `video_streamer.py` los conecta al ciclo de vida de la captura.

### Decisión clave: inferencia desacoplada del stream

Hasta v2.5.0 la inferencia YOLO corría **dentro** de `recv()` del track
WebRTC: cada frame del stream esperaba a la red neuronal, así que un modelo
a 120 ms/frame degradaba el video a 8 FPS.

Desde v2.6.0 la inferencia corre en un **loop propio** sobre el último frame
disponible y publica resultados; el stream solo dibuja el último resultado
publicado (primitivas cv2, <1 ms). Consecuencias:

- El video mantiene sus ~30 FPS aunque la visión corra a 2 FPS.
- Las anotaciones pueden ir "atrasadas" respecto al frame mostrado (como
  máximo un ciclo de inferencia). El HUD muestra la latencia real para que
  el desfase sea visible, y los resultados con más de 2 s no se dibujan.
- Los frames que la visión no alcanza a procesar **se descartan** (siempre
  se toma el último, nunca se encola) — la frescura importa más que la
  completitud para controlar un drone.

## 2. Etapas conmutables y sus combinaciones

Cada etapa se enciende/apaga por separado (`POST /api/segmentation/config`,
`POST /api/yolo/config`); el costo en latencia se paga solo por lo encendido:

| Segmentación | Detección | Comportamiento | Latencia típica (CPU, yolov8n@640 / n-seg@416) |
|--------------|-----------|----------------|------------------------------------------------|
| off | off | Video puro, visión inactiva, governor en modo `off` | 0 ms |
| off | on  | Detección clásica: cajas sobre el frame completo | ~120–150 ms |
| on (`overlay`) | off | Solo contornos de regiones — para evaluar la etapa | ~55–90 ms |
| on (`overlay`) | on | Ambas sobre el frame completo, independientes | ~175–240 ms |
| on (`mask`) | on | **Cascada**: la máscara (dilatada `mask_margin_px`) suprime el fondo antes del detector | ~135–175 ms |

El modo `mask` es la razón de ser de la etapa de segmentación: en video
analógico con ruido de la EasyCap, suprimir el fondo antes del detector
reduce falsos positivos. El costo es la inferencia extra; si en la práctica
el detector fine-tuneado solo ya es suficientemente robusto, la etapa se
apaga y esa latencia se recupera. `overlay` existe para poder evaluar la
segmentación sin afectar a la detección.

Ambas etapas comparten **un solo worker** (cascada secuencial): en CPU no
hay cores de sobra para paralelizar dos redes, y la cascada necesita la
máscara antes de detectar de todos modos.

## 3. Presupuesto de latencia extremo a extremo

Para la decisión de control (futuro `autopilot.py`, que vive en el backend)
el tramo WebRTC **no** cuenta — solo el camino cámara → decisión → drone:

| Tramo | Latencia | Fuente |
|-------|----------|--------|
| Cámara FPV + VTX analógico | ~5 ms | despreciable |
| EasyCap (digitalización NTSC) | ~50–100 ms | `CAPTURE_BASE_MS = 75` |
| Pipeline de visión (según etapas) | 0–240 ms | medido, `latency.pipeline_ms` |
| Edad del resultado al decidir | 0–500 ms | medido, `latency.result_age_ms` |
| Decisión + inyección CRSF + uplink ELRS + respuesta del drone | ~200–300 ms | `reaction_time_ms = 250` (estimado, pendiente de medir en Fase 3) |

Total con visión activa: **~330–700 ms** desde que algo aparece delante de
la cámara hasta que el drone reacciona. Esa cifra es la que gobierna a qué
velocidad es seguro volar.

## 4. LatencyGovernor — cómo se comportará el autopilot con visión activa

**Principio: el drone no debe volar más rápido de lo que ve.** Si un
obstáculo aparece a la distancia de seguridad `d`, el sistema tiene que
percibirlo y reaccionar antes de recorrer `d`:

```
v_max = safety_distance_m / (t_captura + t_pipeline + t_edad + t_reacción)
```

Con los valores por defecto (`d = 3 m`, visión a ~440 ms totales) salen
**~6.8 m/s**; si se enciende también la segmentación y el total sube a
~600 ms, baja a ~5 m/s. Encender etapas de visión **reduce automáticamente
la velocidad recomendada** — ese es el compromiso que pedía el diseño: más
percepción a cambio de volar más despacio.

Modos que expone `GET /api/vision/status → governor`:

| Modo | Condición | Comportamiento previsto del autopilot |
|------|-----------|----------------------------------------|
| `off` | Ninguna etapa activa | La visión no gobierna: vuela con límites de telemetría solamente (los modos que requieran visión — Follow — no disponibles) |
| `warming_up` | Etapas activas, sin resultados aún | No despegar / no iniciar misión |
| `active` | Resultados frescos | Limitar velocidad comandada a `max_speed_ms` |
| `stale` | Último resultado > `stale_after_ms` (1.5 s) | **Hover inmediato** hasta recuperar visión; si persiste, Return-to-safe |

Parámetros ajustables en runtime (`POST /api/vision/governor`):
`safety_distance_m` (default 3.0 — interior/whoop) y `reaction_time_ms`
(default 250 — re-medir cuando exista la inyección de comandos de Fase 3).
Techo y piso: 8 m/s (límite físico aprox. del Mobula8) y 0.3 m/s (por
debajo, hover).

### Reglas de integración para `autopilot.py` (Fase 4)

1. **La telemetría manda, la visión es señal lenta.** El lazo rápido
   (actitud/hover, ~30–60 ms de latencia CRSF) se cierra con telemetría; la
   visión solo aporta objetivos y vetos a su propio ritmo (decisión ya
   registrada en `ARCHITECTURE.md` §7).
2. Leer `governor.max_speed_ms` **antes de cada comando de velocidad** y
   saturar la consigna con él.
3. Tratar `stale` como evento de seguridad (hover), no como dato viejo
   utilizable.
4. **Degradar antes que perder frescura**: si `vision_fps` cae por debajo
   de ~2, preferir bajar `imgsz` o apagar la segmentación (recuperando
   velocidad de inferencia) antes que aceptar resultados stale.
5. Registrar en el log de decisiones (`safety` del roadmap) el modo del
   governor vigente en cada comando emitido.

### Alternativas consideradas (y por qué no ahora)

- **Compensación predictiva** (extrapolar posición de detecciones con un
  filtro Kalman usando la actitud CRSF): reduce el efecto de la latencia
  sin bajar la velocidad, pero exige estimación de ego-movimiento fiable.
  Candidata para Fase 4 una vez haya datos de vuelo reales; el límite de
  velocidad es la versión conservadora y verificable hoy.
- **Inferencia en GPU/Jetson**: ataca la causa raíz (t_pipeline) — ya está
  en el roadmap como salida prevista si la CPU se queda corta.
- **Post-proceso offline** de la grabación MP4: sin restricción de latencia,
  útil para análisis, no para control. Sigue disponible por diseño (la
  grabación guarda el frame limpio, sin overlay).

## 5. Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/vision/status` | Estado completo: etapas, latencias por etapa, FPS de visión, governor |
| `GET` | `/api/vision/models` | Modelos disponibles por etapa (defaults + `models/`) |
| `POST` | `/api/segmentation/config` | `enabled`, `model`, `confidence`, `focus_mode` (`mask`/`overlay`), `imgsz` |
| `POST` | `/api/yolo/config` | `enabled`, `model`, `confidence`, `imgsz` |
| `POST` | `/api/vision/governor` | `safety_distance_m`, `reaction_time_ms` |
| `GET` | `/api/yolo/status`, `/api/yolo/models` | Rutas históricas del detector (compatibilidad) |

## 6. Pendiente de validación con hardware real

- FPS de visión alcanzables con el stream EasyCap real (las cifras de este
  documento vienen de frames sintéticos en el laptop de desarrollo).
- Si el modo `mask` reduce falsos positivos en video analógico real o si un
  detector fine-tuneado solo (ver `YOLO_FINETUNING.md`) hace innecesaria la
  etapa de segmentación.
- `reaction_time_ms` real, medible solo cuando exista la inyección de
  comandos (Fase 3).
