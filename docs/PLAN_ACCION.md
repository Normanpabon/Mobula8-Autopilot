# Plan de acción — video NTSC y control desde Linux

Actualizado: 2026-09-21. Fuente: revisión de v2.7.0 y correcciones de v2.7.1
en captura/grabación.
captura/grabación. El diagnóstico inicial se conserva en
[REVISION_DEBIAN13.md](REVISION_DEBIAN13.md); este archivo indica qué está
implementado y qué falta aprobar. Los cambios implementados no equivalen a
pruebas satisfactorias con capturadora, gafas y radio reales.

## Objetivo y orden

Conservar el detalle de la salida NTSC de las Cobra X, mostrar el formato
real en el servidor y guardar clips reproducibles. Después validar telemetría
y resolver la entrada RC hacia la TX12 antes de cualquier prueba de vuelo.

| Orden | Trabajo | Estado | Criterio de cierre |
|---|---|---|---|
| 1 · P0 | Formato real de captura → WebRTC → grabación | Implementado; prueba física pendiente | Array, API, track y archivo coinciden en resolución; FPS pedidos, nominales y medidos diferenciados. |
| 2 · P0 | Grabación: encoder, cierre, tomas distintas | Implementado; prueba física pendiente | Tomas de 10 s, 60 s y 5 min decodificables; duración ±5%; reinicios sin sobrescritura. |
| 3 · P1 | Diagnóstico NTSC, color, entrelazado y latencia | Pendiente | Referencia V4L2/FFmpeg y navegador comparadas; señal estable y latencia medida. |
| 4 · P1 | Robustez USB/Linux | Pendiente | Pérdida/reconexión y driver bloqueado gestionados sin congelar servicio. |
| 5 · P0 antes de RC | Corregir pérdida de mando y serial | Pendiente | Ningún comando viejo revive tras timeout, desconexión o cambio de fuente. |
| 6 · P0 antes de RC | Confirmar transporte de entrada RC | Pendiente | Canales comandados observables en Receiver de Betaflight, no solo contador de bytes. |
| 7 · P1 | Prueba integrada con visión y grabación | Pendiente | FPS, duración y latencias documentados bajo carga; fallos seguros verificados. |

## Implementado en esta entrega

- [x] Preset inicial NTSC **720×480 a 30000/1001 FPS** en API y navegador;
  presets alternativos 640×480, PAL 720×576/25 y HD para dispositivos que
  lo soporten. Configuración guardada `ntsc: true`.
- [x] V4L2 preferente en Linux, apertura/configuración fuera del event loop
  y hasta diez intentos de lectura inicial. No se fuerza un estándar
  analógico del driver: seleccionar NTSC en hardware sigue siendo una prueba.
- [x] Dimensiones tomadas de `frame.shape`; FPS nominales del driver o
  fallback solicitado si no son válidos. La UI avisa si se negoció otro modo.
- [x] FPS efectivos medidos, error por pérdida de frames devueltos y rechazo
  de cambio inesperado de geometría. Un `read()` bloqueado sigue siendo
  una limitación: hace falta aislamiento/timeout real del driver.
- [x] Visualización 4:3 por defecto, seleccionable 16:9 o píxeles originales;
  solo cambia la presentación. No se reescala el frame para inferencia o
  archivo. Cambiar a 720p no inventa detalle de una señal analógica.
- [x] Grabación con geometría real, verificación de ambos encoders, nombres
  únicos por toma, tarea única, start idempotente y cierre en stop/shutdown.
  Cambiar captura durante grabación se rechaza; reconectar con el mismo
  formato no reinicia la toma.
- [x] Errores y ruta de la última toma visibles en UI; cronómetro basado
  en estado del servidor. Archivo cerrado no significa archivo validado:
  todavía se requiere ffprobe/reproducción para cada prueba de aceptación.
- [x] Regresiones automatizadas en `tests/test_video.py`, usando imágenes
  sintéticas y writer/decoder OpenCV reales, además de API y track aiortc.

## Etapa 1 — Captura y calidad con las Cobra X

1. Registrar entorno Python, kernel, VID:PID/driver, revisión de las gafas,
   entrada Composite y cable/pinout AV. Comandos en revisión, etapa A.
2. Cerrar consumidores de la cámara. Enumerar con `v4l2-ctl --list-devices`
   y consultar `--all`, `--list-inputs`, `--list-standards` y
   `--list-formats-ext` para el nodo real.
3. Probar **720×480/29.97** únicamente si el driver lo ofrece; comparar
   640×480 cuando sea necesario. Si el driver negocia otra dimensión,
   conservarla y registrar la diferencia. NTSC/Composite se configura en
   el driver si este ofrece el control; algunos dispositivos autodetectan.
4. Guardar 30 s con FFmpeg, reproducir y comparar con las gafas. Revisar
   sincronismo, ruido RF, colores, bordes y texto OSD antes de aplicar filtros.
5. En servidor elegir el dispositivo y preset NTSC. Observar la línea de
   resolución/FPS y verificar proporción con un objeto circular. Usar
   16:9 solo si corresponde a la cámara; el default 4:3 es ajustable.
6. Si hay dientes en objetos en movimiento, ensayar desentrelazado en una
   copia y medir latencia. No añadir nitidez agresiva o escalado al pipeline
   antes de disponer de esta referencia.

**Entregable:** clip de referencia, salida V4L2 y una tabla con resolución,
FPS nominales/medidos, proporción y latencia de varias muestras.

## Etapa 2 — Persistencia del video

- [ ] Grabar 10 s, 60 s y 5 min sin visión, detener y comprobar pista,
      frames, duración, inicio/mitad/final y decodificación completa.
- [ ] Grabar tres tomas en la misma sesión y comprobar que ninguna anterior
      cambió. Repetir stop/start rápido y start repetido.
- [ ] Detener captura y usar Ctrl+C mientras se graba; comprobar archivo
      reproducible y dispositivo liberado.
- [ ] Desconectar capturadora durante toma; exigir error visible y archivo
      cerrado. Un driver que se bloquee puede impedir cierre: registrar el
      caso y resolverlo en etapa 3 antes de darlo por aprobado.
- [ ] Repetir con YOLO y después segmentación. Medir duración real frente a
      duración codificada, FPS y latencia; la cadencia actual es fija.
- [ ] Añadir manifiesto por toma con timestamps y asociación al JSON;
      coordinar rotación de sesiones. Actualmente la relación es el ID
      incluido en el nombre, no sincronía temporal por frame.
- [ ] Añadir listado/descarga de videos y comprobación automática posterior
      al cierre. La UI actual muestra una ruta del servidor, no un enlace.
- [ ] Definir necesidad de recuperación tras corte de energía; si se
      requiere, elegir segmentación/contenedor adecuado y ensayar recuperación.

Comprobación manual (sustituir por la ruta que muestra la interfaz):

```bash
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=codec_name,width,height,avg_frame_rate,nb_read_frames:format=duration,size \
  -of json /ruta/video.mp4
ffmpeg -v error -i /ruta/video.mp4 -f null -
```

Exigir pista de video y `nb_read_frames > 0`; un exit code 0 de ffprobe no
basta (el MP4 vacío original también lo devolvía). No hay captura de audio.

## Etapa 3 — Recuperación de captura en Linux

- [ ] Enumerar nodos/capacidades sin abrir una capturadora ocupada, admitir
      `/dev/v4l/by-id/…` y evitar depender de índices que cambian.
- [ ] Sustituir el timeout aparente del ThreadPoolExecutor por un aislamiento
      que pueda interrumpir apertura/lectura del driver sin liberar una
      captura mientras otro thread la utiliza.
- [ ] Implementar reconexión con espera progresiva y estado explícito.
- [ ] Probar permisos de video, desconexión USB y consumo concurrente.
- [ ] Medir estabilidad 15 min y guardar inventario/logs en cada ejecución.

## Etapa 4 — Preparar el control (bloquea pruebas físicas de inyección)

- [ ] Al perder gamepad/foco/WS, neutralizar consignas y exigir recuperación
      explícita con throttle bajo. El código RC actual conserva valores.
- [ ] Evitar que un comando parcial después del deadman reactive throttle
      o AUX anteriores. Center debe tener prioridad sobre la lectura gamepad.
- [ ] Calibrar ejes/mapeo, seleccionar dispositivo y exigir un único dueño
      del canal de mando. El stick centrado de un gamepad no es throttle bajo.
- [ ] Usar reloj monotónico y escritura serial acotada; limpiar connected y
      reabrir el puerto tras desconexión. Mostrar canales enviados, no solo
      consignas almacenadas.
- [ ] Validar telemetría real con puerto `/dev/serial/by-id/…`, CRC y valores
      plausibles durante 5 min, guardando JSON. No basta abrir el puerto.

## Etapa 5 — Transporte y banco RC desde Linux

1. Identificar versión EdgeTX/ELRS y entradas realmente soportadas. Telem
   Mirror no acredita entrada RC; USB Joystick es radio → Linux.
2. Ensayar entrada compatible documentada. La prueba de direcciones CRSF
   por VCP es solo un experimento acotado cuando haya fundamento de soporte.
   Si no lo hay, diseñar adaptador trainer compatible o interfaz a módulo
   ELRS externo, con niveles/pinout/failsafe/prioridad del piloto definidos.
3. Primero solo radio; después FC desarmada y **sin hélices**. Confirmar
   AETR y AUX de desarmado, mover ejes cerca del centro y observar Receiver
   en Betaflight manteniendo throttle al mínimo.
4. Ensayar cierre de navegador, pérdida de red/gamepad/USB, muerte del
   proceso y pérdida de RF. Medir respuesta real en FC y recuperación del
   piloto. El deadman del PC no actúa si el proceso está muerto.
5. Repetir con visión+grabación bajo carga. Solo tras aprobar todos los
   fallos se redacta un plan separado de vuelo.

**Entregable:** matriz consigna/canal recibido, tiempos hasta failsafe,
prioridad de mando y recuperación; versiones y resultado de cada ensayo.

## Verificación de software

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
node tests/test_video_player.mjs
```

Ejecutar en un entorno aislado. Las pruebas no abren la capturadora ni
escriben a la radio; los videos temporales se eliminan al finalizar.


Resultado de esta entrega: 10 pruebas Python y 3 JS aprobadas. Se verificó
WebRTC en navegador con fuente sintética rotulada y se grabó un MP4 de
720×480/29.97 FPS, 1451 frames, 48.415 s y 3 986 552 bytes; FFmpeg lo
decodificó completo sin errores. No es evidencia de calidad RF/NTSC real.
