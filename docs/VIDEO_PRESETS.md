# Presets de captura analógica y digital

## Diagnóstico del código anterior

Al elegir otra cámara se conservaba la solicitud NTSC de 720×480/29,97 FPS
(tanto en frontend como en API), la presentación 4:3 y la calibración global
`brightness=64`, `contrast=54`, `saturation=128`, `gamma=0.9`. Esa calibración
pertenece a la captura analógica; no es una configuración universal para una
webcam. La enumeración mostraba el modo inicial del driver como si describiera
la capacidad de la cámara. No se negociaban modos digitales alternativos.

Estas son causas verificadas en el código, no una medición de la cámara del
laptop del usuario. OpenCV advierte que los valores solicitados dependen del
hardware, driver y backend: [propiedades de captura](https://docs.opencv.org/4.13.0/d4/d15/group__videoio__flags__base.html).

## Dos presets

| Preset | Solicitud | Presentación | Color |
|---|---|---|---|
| Analógico | NTSC 720×480/29,97 o PAL 720×576/25 | 4:3, modificable para cámaras 16:9 | Calibración analógica existente |
| Digital (predeterminado) | Negociar hasta 1920×1080/30 | Proporción del frame recibido | Valores del dispositivo; gamma y balance neutros por defecto |

Digital prueba 1080p y 720p con MJPEG y con el formato predeterminado del
driver, más el modo inicial como alternativa. Evalúa las dimensiones de los
frames, conserva el mejor modo obtenido hasta 1080p y avisa si difiere del
objetivo. No crea detalle mediante reescalado. El diagnóstico `negotiation`
incluye intentos y resultados; `pixel_format` informa el FOURCC del driver.
No es una enumeración exhaustiva de todas las capacidades del hardware.

La solicitud y el formato real se mantienen separados. WebRTC, visión y
archivo parten de los frames con sus dimensiones reales. La interfaz muestra
resolución de captura, FPS nominales/medidos y resolución recibida por el
navegador. El nombre del dispositivo ya no presenta su resolución inicial
como si fuera su máximo soportado.

Cambiar de puerto o preset con el stream activo reinicia la captura usando
la nueva selección. Durante una grabación, los cambios quedan bloqueados
para conservar la geometría del archivo. Reconectar al mismo dispositivo y
preset no reinicia la captura. La calibración digital se guarda en `digital`
dentro de video_config.json, separada de los valores analógicos históricos.
Los sliders de color del driver se deshabilitan en el preset digital; la API
admite una calibración digital explícita si se conocen los rangos del dispositivo.

## API

- `POST /api/video/start {"device_id": 0, "profile": "digital"}`: adaptativo.
- `POST /api/video/start {"device_id": 2, "profile": "analog", "standard": "ntsc"}`.
- PAL usa `standard: "pal"` dentro del preset analógico.
- `width` y `height` opcionales deben enviarse juntos; permiten solicitar un
  modo concreto en lugar de negociación adaptativa. `fps` también es opcional.
- `GET /api/video/config?profile=digital` obtiene la calibración correspondiente.
- `POST /api/video/config` acepta `profile`; omitirlo conserva compatibilidad
  con la calibración analógica anterior.

## Aceptación con hardware pendiente

1. Laptop en Digital: comparar formato solicitado, captura real y navegador.
   Si entrega 720p, verificar que la cámara soporta 1080p antes de considerarlo
   un fallo. Registrar los intentos de negociación y los FPS medidos.
2. EasyCap/Cobra X en Analógico: NTSC/PAL según la señal. Comprobar color y
   proporción sin alterar las dimensiones del archivo.
3. Fuente digital externa: verificar que su salida y la capturadora entreguen
   video USB compatible. El preset no implementa un protocolo propietario de
   Walksnail ni garantiza que cualquier receptor pueda conectarse por USB.
4. Grabar 10 s/60 s/5 min y examinar resolución, duración y FPS con ffprobe;
   decodificar con ffmpeg. Comparar detalle del archivo y del navegador.
5. Si captura y archivo son nítidos pero WebRTC no, medir bitrate, pérdidas,
   codec y carga de CPU. La resolución por sí sola no garantiza calidad: el
   encoder y el ancho de banda también intervienen. No se alteraron límites
   internos de aiortc ni se eliminaron mecanismos de adaptación de red.

Permanece la limitación conocida de un driver bloqueado dentro de cap.read():
este cambio no sustituye el aislamiento pendiente de la captura en un proceso.
