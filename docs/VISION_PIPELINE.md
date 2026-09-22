# Pipeline de visión YOLO26

El pipeline tiene tres modos excluyentes:

```text
captura ─────────────────────────────── WebRTC + grabación limpia
   └── último frame → worker de visión → resultado → overlay / governor
                       OFF: sin inferencia
                       DETECT: YOLO26n → cajas
                       SEGMENT: YOLO26n-seg → cajas y máscaras
```

`VisionModel` carga un modelo y normaliza resultados en `Detection`. SEGMENT
extrae cajas y polígonos de la misma llamada. No hay preprocesador SEG→DET ni
procesadores independientes. Las máscaras se construyen desde `masks.xy`,
que conserva las coordenadas de la imagen original tras quitar letterboxing.

`VisionPipeline` conserva un solo executor, la selección ROI 12×8, recorte de
su envolvente, enmascarado de huecos y traducción de cajas al frame completo.
Descarta cajas cuyo centro queda fuera de ROI o cuya área seleccionada es
menor a la mitad. Recorta máscaras y overlay a las celdas seleccionadas.
Selección vacía pausa inferencia. El frame original no se modifica.

`annotate()` solo dibuja el resultado publicado; nunca carga ni infiere. La
grabación sigue recibiendo frames limpios. No dibuja resultados de otra
resolución, revisión ROI/configuración o con más de dos segundos de edad.

## Configuración

`backend/config/vision.json` contiene defaults versionados y recibe los cambios
persistidos desde la API. Revisar el diff antes de commitear ajustes locales.
Modo inicial: detect; carga en el worker al iniciar captura, sin bloquear
WebRTC. Si falla, status muestra el error y governor queda en warming_up.
OFF permite operar sin Ultralytics. Reintentar aplicando configuración.

```http
GET /api/vision/config
POST /api/vision/config
```

El POST acepta un objeto parcial, por ejemplo:

```json
{
  "pipeline_mode": "segment",
  "imgsz": 416,
  "enabled_classes": ["person", "cow"],
  "confidence": {"default": 0.45, "per_class": {"cow": 0.4}}
}
```

También acepta la estructura completa del archivo. `imgsz` escalar afecta al
modo seleccionado; usar `{ "detect": 416, "segment": 640 }` para ambos.
`profile: "analog"` aplica 416/416; `profile: "digital"` aplica 640/640. Estos
presets son explícitos e independientes del perfil de captura, para permitir
comparaciones controladas. `imgsz` explícito tiene prioridad sobre el preset.
Las clases se resuelven desde `model.names`; nombres desconocidos impiden
activar el modelo. Lista vacía deshabilita todas las clases y omite inferencia; el governor queda
en warming_up (velocidad 0), sin publicar percepción fresca artificial.
Los thresholds por clase se reemplazan como un mapa completo; `{}` los limpia.
Inferencia usa el mínimo threshold y luego filtra cada resultado sin redondear
su confidence. Filtrar clases no reduce el backbone de la red.

La carga y warm-up se serializan con inferencia. Un candidato solo sustituye
el modelo anterior tras validar y guardar configuración correctamente. Los
cambios descartan resultados y métricas previas. Puede haber dos modelos
residentes durante la preparación del candidato; solo uno recibe cada frame.
Después del cambio se liberan las referencias del anterior (el allocator de
PyTorch puede conservar memoria reservada). Un fallo mantiene el modelo y el
archivo anteriores. No se promete una conmutación sin pausa de inferencia.

`overlay.boxes`, `overlay.labels` y `overlay.masks` controlan la visualización.
`benchmark.collect_metrics` activa una ventana de percentiles; por defecto
30 segundos y máximo 10.000 muestras. Configuraciones inválidas devuelven 422,
fallos de carga/persistencia 503. En OFF, validar nombres contra pesos se
pospone hasta la siguiente activación.

## API y UI

El panel AI aplica un único modo y permite editar modelo por tarea, tamaños,
clases, confidence global y thresholds. Muestra modo/modelo efectivos, latencia
de inferencia, pipeline, edad de resultado, FPS, detecciones y Vmax.

`GET /api/vision/status` expone esos valores en el nivel superior; conserva
`detection`, `segmentation`, `latency`, `roi` y `governor`. `metrics` incluye
p50/p95 de inferencia y pipeline. Edad se mide desde finalización del resultado;
el tiempo de pipeline se agrega por separado al cálculo del governor.

Rutas heredadas `/api/yolo/config` y `/api/segmentation/config` seleccionan
respectivamente DETECT y SEGMENT; `enabled:false` selecciona OFF. Ya no se
pueden combinar. `focus_mode` se acepta como compatibilidad de entrada, pero
no cambia el frame ni ejecuta un segundo modelo. La respuesta de configuración
es ahora el esquema unificado; migrar clientes que dependían de `enabled` en
la respuesta. `/api/vision/models` lista modelos locales por convención de
nombre, pero cualquier nombre explícito válido puede cargarse.

## LatencyGovernor

Se conserva la política previa:

- OFF o ROI vacía: sin gobierno por visión.
- Visión solicitada sin resultado: warming_up, velocidad recomendada 0.
- Resultado de más de 1500 ms: stale, velocidad recomendada 0 (HOVER).
- Resultado fresco: `v_max = distancia / (75 ms + pipeline + edad + reacción)`.

Distancia por defecto 3 m, reacción 250 ms, techo 8 m/s y piso histórico 0.3 m/s.
El governor informa una recomendación; no conecta visión con inyección RC.

## Validación

```bash
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.mjs
python scripts/smoke_yolo26.py
```

El smoke real descarga pesos si hacen falta y exige cajas y máscaras no vacías
sobre el asset `bus.jpg`. CI incluye estas comprobaciones con Ultralytics 8.4.0;
la ejecución remota de CI requiere publicar la rama. Ver
[benchmark reproducible](../benchmarks/README.md) e
[informe de migración](YOLO26_MIGRATION_REPORT.md). No dar por aceptada la
calidad de campo ni la latencia con WebRTC y grabación reales hasta medirlas.
