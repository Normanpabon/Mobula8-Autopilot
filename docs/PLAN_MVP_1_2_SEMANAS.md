# Plan de desarrollo del MVP — 1 a 2 semanas

Fecha base: 2026-09-21. Repositorio: `dev_npabon`, commit `8997aec`
(`2.7.1`).

## Objetivo del MVP

Cerrar una estación terrestre usable y demostrable para el Mobula8 que:

1. reciba y visualice telemetría CRSF de la TX12;
2. capture el video FPV real de la EasyCap, lo entregue por WebRTC y lo
   grabe en clips MP4 reproducibles;
3. guarde sesiones JSON asociadas a las grabaciones;
4. ejecute visión opcional sin degradar el stream;
5. sobreviva a desconexiones y cierre de forma segura;
6. deje documentada la decisión sobre la ruta de control RC.

El vuelo autónomo queda fuera de este MVP. No se debe declarar control RC
validado hasta observar los canales en la TX12/Betaflight y aprobar los
casos de pérdida de conexión sin hélices.

## Estado de partida

- La arquitectura ya está separada en `backend/`, `frontend/`, `docs/`,
  `tests/` y datos de runtime ignorados (`logs/`, `models/`).
- Telemetría, sesiones, WebRTC, captura/grabación, YOLO/segmentación y panel
  RC están implementados en software.
- La corrección 2.7.1 ya cubre geometría negociada, FPS real, writer único,
  nombres de toma, cierre en shutdown y estado visible en UI.
- Las pruebas JavaScript pasan (3/3) y el backend compila, pero el entorno
  actual no tiene las dependencias Python del proyecto; por eso las pruebas
  Python no arrancan.
- No hay evidencia de aceptación con EasyCap/Cobra X/TX12/Mobula8 reales.
- Existe un MP4 histórico vacío de 258 bytes y sin pistas; no es una
  grabación válida ni debe usarse como evidencia de funcionamiento.

## Prioridad y criterio de corte

El orden de trabajo es: entorno reproducible → telemetría → captura y
grabación → robustez → visión → validación RC de banco. Si el hardware RC o
la entrada soportada por EdgeTX no están disponibles, se cierra el MVP sin
control RC y se entrega una matriz de bloqueo explícita.

## Plan por días

### Días 1–2 — Entorno y baseline reproducible

- Crear/activar un entorno Python 3.11 siguiendo `docs/SETUP.md`.
- Instalar `requirements.txt`, `requirements-test.txt` y dejar YOLO como
  instalación opcional hasta que el stream base esté estable.
- Registrar versión de Python, kernel, OpenCV, aiortc, PyAV, FastAPI, driver
  V4L2, VID:PID de EasyCap, TX12/EdgeTX y rutas `/dev/v4l/by-id` y
  `/dev/serial/by-id`.
- Ejecutar `compileall`, las pruebas Python y JavaScript; guardar el resultado
  como baseline.
- Confirmar que el servidor arranca con y sin TX12 conectada y que el
  frontend carga sin 404 ni errores de consola.

**Salida:** entorno reproducible, inventario de hardware y lista de fallos
iniciales.

### Días 3–4 — Telemetría y sesiones

- Validar `GET /api/status`, `/api/latest`, `/api/history`, `/api/sessions` y
  `WS /ws` con datos reales.
- Confirmar timestamps, conteo de frames, guardado y recuperación de una
  sesión.
- Probar desconexión y reconexión de la TX12 sin reiniciar el servidor.
- Corregir únicamente fallos P0 que impidan iniciar, recibir o guardar datos;
  no ampliar el esquema de sesiones durante esta fase.

**Salida:** sesión JSON real inspeccionada y evidencia de reconexión o bloqueo
documentado.

### Días 5–6 — Captura, WebRTC y grabación

- Enumerar capacidades reales con `v4l2-ctl`; usar la ruta estable del nodo
  cuando exista, no depender solo de `/dev/video0`.
- Probar NTSC 720×480/29.97 y una alternativa soportada por el driver.
- Confirmar que resolución solicitada, negociada, track WebRTC y writer se
  reportan por separado y coinciden donde deben.
- Ejecutar tomas de 10 s, 60 s y 5 min; repetir tres tomas en una sesión,
  stop/start rápido y Ctrl+C durante grabación.
- Validar cada MP4 con `ffprobe` y `ffmpeg -f null -`; exigir pista, frames,
  duración dentro de ±5% y decodificación completa.
- Medir latencia percibida y FPS nominal/medido; registrar color, proporción,
  entrelazado y estabilidad de la señal.

**Salida:** clips de referencia, tabla de formato/FPS/latencia y veredicto
OK, OK con ajuste o falla.

### Días 7–8 — Robustez de captura y cierre del MVP base

- Probar desconexión de EasyCap durante captura y grabación.
- Verificar que el servidor no queda bloqueado, que el writer se cierra y que
  el dispositivo puede reabrirse.
- Si el driver bloquea `read()`, aislar el problema y documentar la limitación;
  no dar por resuelta una reconexión basada solo en un timeout aparente.
- Mostrar en UI el error accionable y la ruta de la última toma cerrada.
- Ejecutar toda la regresión automatizada desde el entorno reproducible.

**Salida:** MVP base aceptado o una lista corta de defectos P0/P1 con
reproducción.

### Días 9–10 — Visión opcional y rendimiento

- Activar YOLO sobre video real y medir detección sola.
- Comparar segmentación `overlay` y `mask`; medir FPS de visión, latencia y
  edad del resultado.
- Confirmar que el stream mantiene sus FPS con la inferencia desacoplada.
- Verificar el estado `stale`/`HOVER` del `LatencyGovernor` bajo carga.
- Decidir para el MVP si se entrega detección sola, cascada completa o visión
  desactivada por defecto. La decisión debe basarse en medidas reales, no en
  las cifras sintéticas de la documentación.

**Salida:** matriz de rendimiento y configuración recomendada por defecto.

### Días 11–12 — RC de banco y entrega

- Antes de conectar el drone, validar solo TX12 y probar las direcciones CRSF
  configurables (`0xEE`, `0xEA`, `0xC8`).
- Si una ruta funciona, comprobar throttle bajo, neutralización al perder
  foco/gamepad/WS/USB, bloqueo de consignas antiguas y telemetría simultánea.
- Repetir con el FC encendido y sin hélices; observar canales AETR en
  Betaflight y medir timeout/failsafe.
- Si ninguna ruta es aceptada, registrar el resultado y detener la expansión
  de RC; evaluar después trainer/adaptador o módulo ELRS externo.
- Actualizar `ROADMAP.md`, `PLAN_ACCION.md`, `HARDWARE_VALIDATION.md` y el
  changelog con evidencia, no con supuestos.

**Salida:** release candidate del MVP, checklist firmado y riesgos restantes.

## Definición de terminado

- `python -m unittest discover -s tests -v` y `node tests/test_video_player.mjs`
  pasan desde un entorno documentado.
- El dashboard carga sin errores y expone estado real de telemetría, video y
  grabación.
- Hay al menos una sesión JSON y tres MP4 reales reproducibles, con metadatos
  de resolución, FPS y duración.
- Se ha probado al menos una desconexión de TX12 y de EasyCap, o el bloqueo
  queda reproducido y clasificado como P1 con workaround.
- La visión tiene una configuración por defecto justificada por mediciones.
- El control RC está validado en banco o explícitamente marcado como no
  soportado por la ruta TX12 probada. Nunca se prueba con hélices durante este
  plan.

## Riesgos que pueden ampliar a dos semanas

- Falta de acceso al hardware, permisos `video`/`dialout` o driver V4L2.
- Dependencias pesadas de PyAV/aiortc/OpenCV o incompatibilidad con Python
  distinto de 3.11.
- `read()` bloqueante del driver que impida reconexión limpia.
- EdgeTX/Telem Mirror sin entrada RC PC → radio; el código existente no
  demuestra que el transporte sea soportado.
- Inferencia YOLO demasiado lenta para el equipo disponible.

## No hacer dentro de este MVP

- Implementar `autopilot.py`, PID, navegación, follow-target o despegue.
- Hacer fine-tuning/exportación de modelos antes de medir el pipeline base.
- Exponer el servidor fuera de la LAN sin autenticación.
- Declarar "control de vuelo" a partir de bytes escritos o contadores del
  backend; la aceptación exige observar el receptor.
