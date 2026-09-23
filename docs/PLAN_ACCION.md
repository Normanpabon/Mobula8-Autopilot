# Plan de aceptación de la alfa

Actualizado: 2026-09-23. Esta lista separa funciones implementadas de resultados que aún requieren el equipo real. No se declara vuelo autónomo ni control RC validado.

## Estado actual

| Área | Implementado en software | Evidencia que falta |
|---|---|---|
| Serial y sesiones | Selector de puerto, reconexión, contadores de bytes/CRC/tipos, indicador de telemetría reciente, logs y JSON con checkpoints | Sensores reales visibles en EdgeTX, API y navegador durante una sesión; reconexión física de TX12 |
| Captura y MP4 | Presets Digital/Analógico, dimensiones negociadas, WebRTC, writer único, cierre y nombres únicos | Comparación de fuente con navegador; clips de 10 s, 60 s y 5 min decodificables; desconexión USB |
| Visión | YOLO26 DETECT/SEGMENT, ROI, resultados desacoplados del stream, métricas y governor | p50/p95 de latencia y FPS con la misma señal en OFF, DETECT y SEGMENT, con y sin grabación |
| RC | Estado completo de canales, propietario/época, throttle mínimo al perder mando y reconexión serial que deja RC deshabilitado | Entrada soportada por la TX12, canales AETR observados en Betaflight y respuesta ante fallos, sin hélices |

La última inspección de logs seriales encontró frames CRSF `0x3A` de sincronización, pero cero muestras de telemetría de aeronave. Abrir el puerto y recibir esos frames no confirma un enlace de sensores. Configurar y verificar primero la salida de telemetría de EdgeTX y el enlace RF; después comparar `serial_bytes_received`, `serial_valid_frames`, `frames_received` y `telemetry_active` en `/api/status`.

## Secuencia mínima de aceptación

1. **Entorno:** registrar Python, sistema, versiones EdgeTX/ELRS, ruta estable de serial y capturadora, driver y formato V4L2/DirectShow. Arrancar con y sin TX12. Revisar logs de aplicación y sesiones JSON.
2. **Telemetría:** confirmar sensores en la TX12; conectar el puerto apropiado y comprobar muestras en `/api/latest`, `/api/history`, `/ws` y dashboard durante cinco minutos. Desconectar y reconectar la radio sin reiniciar el servidor.
3. **Video base:** probar Digital y Analógico según el dispositivo. Registrar resolución/FPS solicitados, negociados, enviados y recibidos, proporción, color y latencia de fuente a navegador. Comparar con captura local antes de ajustar el pipeline.
4. **Grabación:** hacer tomas de 10 s, 60 s y 5 min; repetir tres tomas en la misma sesión y un cierre del servidor durante grabación. Exigir pista, frames, duración cercana al tiempo real y decodificación completa con `ffprobe` y `ffmpeg`. Revisar el inicio, medio y final del archivo.
5. **Robustez USB:** retirar la capturadora durante una toma y comprobar error visible, cierre del archivo y reapertura del dispositivo. Una llamada bloqueada en `cap.read()` sigue pendiente de aislamiento en proceso; documentar la reproducción si aparece.
6. **Visión:** con la misma señal y equipo, medir OFF, DETECT y SEGMENT, con y sin grabación. Registrar p50/p95 de captura a presentación, FPS capturados/decodificados, edad de resultado y CPU/GPU. Elegir modo de campo a partir de esas medidas; OFF es el valor inicial de una instalación nueva.
7. **RC de banco:** identificar una interfaz de entrada oficialmente soportada por la TX12. Primero radio sola; después controlador de vuelo desarmado y **sin hélices**. Confirmar AETR y AUX en Betaflight, pérdida de gamepad/foco/red/USB/proceso y prioridad del piloto. `frames_sent` no acredita canales recibidos. Si no hay una ruta de entrada demostrada, mantener RC fuera del uso de campo.

Comprobación de cada MP4 (sustituir la ruta):

```bash
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=codec_name,width,height,avg_frame_rate,nb_read_frames:format=duration,size \
  -of json /ruta/video.mp4
ffmpeg -v error -i /ruta/video.mp4 -f null -
```

Una prueba de software satisfactoria o un MP4 generado con fuente sintética no sustituye ninguno de estos pasos. Registrar fecha, equipo, configuración, archivo de evidencia, resultado y defecto reproducible por cada criterio. El plan de control RC se detalla en [RC_INJECTION.md](RC_INJECTION.md).
