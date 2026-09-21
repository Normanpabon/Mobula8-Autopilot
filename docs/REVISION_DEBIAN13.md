# Revisión y plan de pruebas en Debian 13

> Diagnóstico histórico previo a v2.7.1. Los hallazgos descritos aquí
> corresponden al código revisado inicialmente. Para correcciones ya
> implementadas y pendientes actuales consultar [PLAN_ACCION.md](PLAN_ACCION.md).

Fecha: 2026-09-21. Base: v2.7.0, commit `e35eefb`, **más los cambios locales
ya preparados en `backend/video_streamer.py`**. Esta revisión no modifica
el código de ejecución ni da por aprobadas pruebas con hardware.

## 1. Estado y evidencia

El usuario reporta una prueba casi exitosa de video en Debian 13, con
problemas de adquisición y sin grabación reproducible. Cadena real:
**Mobula8 → RF analógica → Skyzone Cobra X → salida AV NTSC → capturadora
USB → Linux/OpenCV → WebRTC y grabación**. Aún no se ha probado el control.

| Área | Resultado de esta revisión |
|---|---|
| Captura y WebRTC | Implementados; funcionamiento parcial reportado por el usuario, sin mediciones guardadas de resolución/FPS/latencia reales. |
| Grabación | Existe `logs/video/video_20260921_182948.mp4`: **258 bytes, `nb_streams=0`, sin duración** según `ffprobe`. Es un contenedor vacío, no un video recuperable desde ese archivo. |
| Formato | `video_config.json` contiene `ntsc: false`; el código solicita 25 FPS al driver. La API y la UI siguen solicitando 1280×720/30 por defecto. El cambio local a 720×480 no alcanza esas capas. |
| Control | Generador CRSF, API y panel implementados. No hay evidencia de recepción de consignas por TX12/FC. Escribir bytes por USB no demuestra control. |
| Entorno de la revisión | Debian 13; Python activo de conda 3.14.7 sin cv2/aiortc/av/fastapi/serial/numpy. Python del sistema tampoco tiene cv2/aiortc/av. No aparecen nodos `/dev/video*`, `/dev/ttyACM*` ni `/dev/ttyUSB*` accesibles. |
| Alcance de verificación | Archivo inspeccionado con ffprobe; sintaxis Python analizada; pruebas aisladas de clases/funciones con dependencias simuladas. No se ejecutó el servidor completo ni se probó hardware. |

No hay registros de consola de la última prueba en el repositorio que
permitan reconstruir la resolución realmente negociada. El desajuste de
resolución es una **causa probable**, no una causa histórica demostrada.
Los modelos `yolov8n.pt` y `yolov8n-seg.pt` están sin seguimiento de Git;
se conservaron, igual que el cambio preparado de captura.

## 2. Hallazgos y prioridades

### P0 — Grabación: tamaño solicitado distinto del frame real

`VideoCapture.start()` guarda width/height/fps solicitados y solo imprime
los valores negociados. `VideoStreamer.start_recording()` usa los primeros
para abrir `VideoWriter`. La UI no ofrece 720×480 (ofrece 640×480, 720p y
1080p), aunque la capturadora puede negociar otra geometría.

Prueba aislada: un driver simulado devolvió 720×480 a 29.97 FPS al solicitar
1280×720/30; `capture.status` siguió anunciando 1280×720/30. OpenCV exige
que cada frame tenga el tamaño declarado al abrir el writer
([documentación](https://docs.opencv.org/4.x/dd/d9e/classcv_1_1VideoWriter.html)).
Esto puede descartar frames aun cuando la vista WebRTC funciona, ya que el
track WebRTC construye sus imágenes desde el array real.

**Corrección pendiente:** geometría desde `frame.shape`, FPS negociados
válidos y medición separada de FPS efectivos; propagar esos valores al
writer, WebRTC y API. Validar cada cambio de tamaño y rechazar o cerrar la
sesión explícitamente si el formato cambia durante la grabación.

### P0 — Grabación: apertura, cierre y repetición no confiables

En `VideoRecorder.start()` el fallback AVI no verifica `isOpened()` y aun
así anuncia `is_recording=True`. El endpoint responde éxito sin comprobar
que se puedan codificar frames. El contador aumenta tras `write()`, que no
confirma persistencia. `mp4v` es MPEG-4 Part 2, aunque el comentario diga H.264.

Además:

- `lifespan()` no llama a `video.stop_capture()` al apagar el servidor;
  falta un cierre explícito del writer y finalización del contenedor.
- Dos grabaciones de una misma sesión reutilizan `video_{session_id}.mp4`;
  la segunda puede sobrescribir la primera.
- El task de `_record_loop()` no se conserva ni cancela/espera al parar;
  un stop/start rápido puede dejar varios loops escribiendo al mismo writer.
- Reiniciar captura mientras se graba puede dejar writer y captura con
  formatos distintos. Debe detenerse o rechazarse ese cambio.
- La UI inicia el cronómetro aunque falle la petición de grabar; al parar
  no muestra la ruta devuelta. No hay descarga/listado de videos en la UI.
- El vínculo con telemetría es el nombre de sesión; no hay timestamps por
  frame ni coordinación al rotar la sesión JSON. No equivale a sincronía
  temporal validada. Una prueba sin telemetría puede dejar video sin JSON.

**Corrección pendiente:** error visible ante fallo de encoder/disco,
nombres únicos por toma, un único task de grabación, cierre en `finally`
del ciclo de vida, y manifiesto con sesión, inicio/fin, formato, frames y
ruta. Aprobar grabación solo después de reabrir y decodificar el archivo.

### P1 — Captura Linux y NTSC

El cambio local mejora nombres desde sysfs y reintenta lecturas al enumerar,
pero la apertura definitiva solo intenta un frame. Enumeración usa V4L2
y captura `CAP_ANY`; escanear índices 0–9 abre dispositivos en paralelo y
puede competir con una captura activa. El timeout de 12 s no es un límite
real: salir del `ThreadPoolExecutor` espera a los workers bloqueados.

`ntsc` solo cambia los FPS solicitados: **no selecciona el estándar
analógico V4L2**. Tampoco está expuesto en `VideoConfigRequest`. La selección
de entrada Composite/estándar debe verificarse en el driver; algunos
adaptadores USB autodetectan y no implementan esas operaciones
([V4L2: estándares](https://docs.kernel.org/userspace-api/media/v4l/standard.html)).

**Corrección pendiente:** enumerar nodos y capacidades V4L2, permitir ruta
estable `/dev/v4l/by-id/…`, no sondear una captura ocupada, apertura fuera
del event loop con estrategia real de timeout, calentamiento acotado,
detección de pérdida de señal y reconexión. Separar formato pedido,
negociado y medido en el diagnóstico.

### P0 antes de control físico — Entrada y pérdida de control

La documentación de EdgeTX describe Telem Mirror como salida de telemetría;
no documenta allí una entrada de canales RC. USB Joystick transmite los
mandos **radio → PC**; no invierte el flujo ni se convierte en PC → radio
mediante un joystick virtual. Ver [hardware EdgeTX](https://manual.edgetx.org/v2.11/bw-radios/radio-settings/hardware)
y [joystick EdgeTX](https://manual.edgetx.org/edgetx-how-to/configure-advanced-joystick-with-edgetx).

Defectos comprobados en pruebas aisladas del código actual:

- `rcReadChannels()` convierte un gamepad centrado en **throttle=1500 µs**.
  Con acelerador a 1756 µs, desconectar el gamepad deja ese mismo valor en
  los sliders y el temporizador continúa enviándolo. El deadman sigue
  recibiendo comandos frescos y no detecta la pérdida del dispositivo.
- `Center` puede ser reemplazado por la siguiente lectura del gamepad.
- El deadman del backend sí envía failsafe al expirar en una salida
  simulada. Sin embargo, no borra las consignas almacenadas: después de
  expirar, actualizar solo yaw reactiva el throttle anterior (1100 µs en
  la prueba). `channels_us` muestra consignas, no necesariamente lo enviado.

Otros riesgos observados: reloj de pared (`time.time`) en el watchdog,
escritura serial síncrona sin `write_timeout`, ausencia de reconexión serial
ni limpieza de `connected` al perder el puerto, y falta de exclusión de
clientes RC. El deadman del proceso no puede actuar si el proceso muere
u ocurre un bloqueo del event loop.

**Corrección pendiente:** armado lógico de la fuente de mando con throttle
bajo, selección/calibración de gamepad y ejes, neutralización y bloqueo al
perder dispositivo/foco/conexión, recuperación explícita sin consignas
viejas, reloj monotónico, escritura acotada, propiedad de la sesión RC y
estado de canales efectivamente transmitidos. Validar la prioridad del
mando físico y el failsafe del receptor independientemente del PC.

## 3. Plan de acción por etapas

### A. Inventario y entorno reproducible

Antes de instalar nada, activar el entorno que se usó en la prueba si aún
existe. Registrar Python, dependencias, kernel, VID:PID y driver de la
capturadora, revisión Cobra X, firmware EdgeTX/ELRS/Betaflight y modelo TX12.
Si se reconstruye el entorno, seguir SETUP con Python 3.11 y requirements.
Las utilidades de diagnóstico Debian son `v4l-utils`, `ffmpeg`, `usbutils`
y, para probar joystick aparte, `evtest`/`joystick`.

```bash
uname -a
python --version
python -m pip freeze
lsusb
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/ /dev/serial/by-id/
python -m serial.tools.list_ports -v
id
```

Si falta acceso, revisar propietario/grupo y ACL del nodo (habitualmente
`video` y `dialout`); ajustar pertenencia si hace falta y volver a iniciar
sesión. No ejecutar el servidor entero como root. Registrar los resultados
junto al log del backend en una carpeta de prueba con fecha.

**Aprobación:** entorno identificado, imports core exitosos y acceso al
nodo de captura y al serial correcto. No asumir `/dev/ttyUSB0`: la radio
puede aparecer como `/dev/ttyACM0`; preferir `/dev/serial/by-id/…`.

### B. Captura independiente: primero la señal real

Con backend, calibrador y otros consumidores cerrados, seleccionar el nodo
real encontrado arriba; `/dev/video0` aquí es solo un ejemplo:

```bash
VIDEO_DEVICE=/dev/video0
v4l2-ctl -d "$VIDEO_DEVICE" --all
v4l2-ctl -d "$VIDEO_DEVICE" --list-inputs
v4l2-ctl -d "$VIDEO_DEVICE" --list-standards
v4l2-ctl -d "$VIDEO_DEVICE" --list-formats-ext
```

Seleccionar entrada Composite y NTSC **solo si el driver los anuncia**;
usar el índice de entrada real (`--set-input`) y estándar anunciado
(`--set-standard`). Si responde operación no soportada, documentar la
limitación y comprobar autodetección. Revisar cable AV/pinout, salida de las
gafas, señal RF, sincronismo y alimentación antes de cambiar color por software.

Objetivo inicial: **720×480, 30000/1001 ≈ 29.97 FPS**, si lo soporta el
adaptador. Si solo ofrece 640×480/30 u otro modo, usar ese modo y anotarlo.
El número de píxeles del display de las gafas no convierte su salida
analógica en HD; pedir 1280×720 no recupera detalle perdido.

Ejemplo **condicionado a que se anuncie YUYV 720×480 a esa cadencia**:

```bash
ffmpeg -n -f v4l2 -input_format yuyv422 -video_size 720x480 \
  -framerate 30000/1001 -i "$VIDEO_DEVICE" -t 30 -an \
  -c:v ffv1 /tmp/mobula8-ntsc-baseline.mkv
ffprobe -v error -count_frames -show_streams -show_format \
  /tmp/mobula8-ntsc-baseline.mkv
ffplay /tmp/mobula8-ntsc-baseline.mkv
```

Elegir otro nombre para repetir: `-n` evita sobrescribir evidencia. Ajustar
formato/tamaño/cadencia según el inventario. La sintaxis V4L2 está en
[FFmpeg Devices](https://ffmpeg.org/ffmpeg-devices.html#video4linux2_002c-v4l2).

**Aprobación:** clip de 30 s decodificable, dimensiones correctas, movimiento
continuo y colores/sincronismo estables. Comparar escena estática y movimiento
con el visor de las gafas. Si hay dientes de entrelazado, comparar una copia
con `bwdif` y medir su coste de latencia; no aplicarlo por defecto a una
capturadora que ya desentrelaza o entrega una señal progresiva. Verificar
aspecto visual de la cámara (p. ej., 4:3), no deducirlo solo de 720/480.

### C. Corregir captura/grabador e integrar WebRTC

Orden de implementación: formato negociado → writer y errores → ciclo de
vida/nombres únicos → preset NTSC en API/UI → diagnóstico/reconexión.
Conservar la toma original y la configuración anterior para comparar.

Después de corregir, iniciar con visión y RC desactivados. La API actual
acepta FPS enteros; el paso a 29.97 coherente exige ajustar ese contrato.
Para ensayar el contrato actual con el índice real (ejemplo: 0):

```bash
curl -f -H 'Content-Type: application/json' \
  -d '{"device_id":0,"width":720,"height":480,"fps":30}' \
  http://localhost:8080/api/video/start
curl -f http://localhost:8080/api/video/status
curl -f -X POST http://localhost:8080/api/video/recording/start
# Esperar 60 segundos observando imagen y contador; luego:
curl -f -X POST http://localhost:8080/api/video/recording/stop
```

Inspeccionar **la ruta que devuelve stop**:

```bash
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=codec_name,width,height,avg_frame_rate,nb_read_frames:format=duration,size \
  -of json /ruta/devuelta/video.mp4
ffmpeg -v error -i /ruta/devuelta/video.mp4 -f null -
```

`ffprobe` puede salir con código 0 incluso para el MP4 vacío encontrado:
exigir una pista de video, `nb_read_frames > 0` y duración coherente. Abrir
y reproducir inicio, mitad y final. No usar solo tamaño o contador de UI.

Matriz de aceptación:

| Prueba | Evidencia requerida |
|---|---|
| Tomas de 10 s, 60 s y 5 min | Pista decodificable, tamaño real, duración dentro de ±5% del cronómetro como objetivo inicial; cuantificar frames perdidos/duplicados. |
| Tres tomas de la misma sesión | Tres nombres distintos; las primeras mantienen tamaño y hash. |
| Stop/start rápido y solicitudes start repetidas | Un solo loop activo; sin duplicación ni sobrescritura. |
| Stop de captura y Ctrl+C durante grabación | Archivo cerrado/reproducible y cámara liberada. |
| Pérdida de capturadora o espacio de disco | Error visible; no anunciar una grabación sana ni perpetuar frames congelados. |
| Cambiar resolución durante grabación | Operación rechazada o toma cerrada y nueva toma con formato correcto. |
| Rotar sesión / prueba solo video | Asociación explícita; no depender de que exista telemetría para conservar el video. |
| Repetir con YOLO y segmentación | Comparar FPS, duración y latencia con la referencia sin visión. |

Una terminación forzada/corte eléctrico no está cubierta por el MP4 actual;
si se requiere tolerancia a eso, evaluar segmentación o contenedor resistente
y probar recuperación. Medir latencia con un reloj/LED visible en origen y
pantalla en una misma toma, varias muestras, antes de usar video para control.

### D. Radio en Linux: lectura antes de inyección

1. **Banco, hélices retiradas.** Primero solo TX12; después Mobula8
   desarmado, con alimentación/ventilación adecuadas. Guardar configuración
   de radio y FC antes de cambiar ajustes; mantener un corte físico accesible.
2. Identificar puerto de datos real y firmware. Elegir USB serial/VCP y
   Telem Mirror según los menús de esa versión; Debug/CLI no es equivalente
   a recibir un stream CRSF de telemetría.
3. Ejecutar desde el entorno preparado:

   ```bash
   python backend/elrs_backend.py --port /dev/serial/by-id/ID_REAL \
     --baud 115200 --host 127.0.0.1
   ```

4. Mantener RC desactivado. Comprobar `/api/status`, `/api/latest`, `/ws`
   y un JSON guardado con valores físicos plausibles. Validar que llegan
   frames con CRC correcto, no solo `connected: true`.
5. Desconectar/reconectar USB. Actualmente se espera encontrar un fallo:
   el reader no reconecta ni limpia el estado. Corregir antes de aprobar
   recuperación automática; no interpretar el indicador como prueba de enlace.

**Aprobación:** telemetría real durante 5 min, sesión legible y pérdida de
puerto visible. Esto valida TX12 → Linux; todavía no valida control inverso.

### E. Decidir y validar el transporte Linux → radio/receptor

1. Revisar si el firmware y puertos disponibles ofrecen una entrada RC
   soportada. No asumir que cambiar `0xEE` por `0xEA`/`0xC8` habilita un
   protocolo que el firmware no implementa.
2. Si se justifica probar CRSF por VCP, hacerlo como experimento acotado,
   inicialmente solo con radio. Registrar firmware, modo USB, dirección,
   baudrate y resultado; observar canales/mixer. Si no hay respuesta, no
   declarar éxito por `frames_sent` ni insistir con pruebas de vuelo.
3. Si no existe entrada por VCP, diseñar una ruta soportada: adaptador de
   PC hacia entrada trainer compatible (PPM/SBUS, según hardware) o interfaz
   CRSF con módulo ELRS externo. Verificar pinout, niveles eléctricos,
   alimentación, firmware y prioridad de mando antes de conectarla. Son
   alternativas pendientes de diseño, no soluciones ya integradas.
4. El modo joystick USB puede probarse **por separado** con `evtest` o
   `jstest` para calibrar TX12 → Linux. No cierra el transporte inverso y
   puede cambiar la disponibilidad de VCP. No asumir que ambos coexisten.

**Aprobación:** ruta de entrada identificada y canales realmente recibidos
en la pestaña Receiver de Betaflight, con FC desarmada y sin hélices. La
pantalla de la radio es evidencia intermedia; la FC es la comprobación final.

### F. Validar mando y fallos, después de corregir los P0 de control

- Comenzar con sliders y una única fuente, no con gamepad. Confirmar orden
  AETR, sentidos, centro 1500, extremos y AUX que mantiene DISARM en este
  modelo; no asumir que AUX bajo siempre significa desarmado.
- Probar roll/pitch/yaw cerca del centro (1450/1500/1550) manteniendo throttle
  mínimo y desarmado. Comparar consigna, frame transmitido y canal recibido.
- Verificar 10 Hz de entrada y 50 Hz de salida sin visión, luego con video,
  grabación y visión. Medir jitter y edad de comando; la API sola no prueba
  que el enlace RF use esa misma cadencia.
- Detener comandos, cerrar pestaña, perder red, desconectar gamepad, cambiar
  foco, quitar USB y cerrar/matar backend, una condición por vez. Registrar
  el estado de los canales en FC, no solo el badge del panel.
- Objetivo inicial del deadman con el proceso sano: failsafe desde ~500 ms
  más un periodo de envío (~20 ms a 50 Hz) y jitter medido. No es una
  garantía de tiempo real ni cubre un proceso muerto.
- Comprobar que una actualización parcial después de timeout no revive
  throttle/AUX viejos; reconexión y Center deben requerir recuperación
  explícita y throttle bajo. Probar el gamepad centrado y luego retirarlo.
- Validar aparte pérdida de RF y corte/prioridad del piloto físico. Definir
  el comportamiento de la ruta seleccionada si Linux desaparece; deshabilitar
  escritura en el PC por sí solo no garantiza recuperar el mando físico.

**Aprobación:** todos los fallos terminan en el estado seguro definido en
radio/FC, sin reactivación automática de consignas antiguas. Solo entonces
preparar otro plan de vuelo; este plan describe pruebas de banco,
no considera el sistema listo para vuelo autónomo.

## 4. Registro mínimo por ejecución

Guardar fecha, commit y diff local, versiones de software/firmware,
VID:PID/driver/rutas USB, fuente NTSC, formato pedido/negociado/medido,
log de backend, respuestas de status, video y salida de ffprobe. Para RC:
consigna, canal observado en FC, edad del comando, tiempo hasta failsafe y
resultado de recuperación. Marcar cada etapa **aprobada / fallida / no
probada**; actualmente B–F siguen pendientes de hardware y/o correcciones.

La comprobación aislada del 2026-09-21 verificó frame CRSF de 26 bytes,
CRC, empaquetado/desempaquetado y timeout contra una salida simulada;
reprodujo además los defectos de formato, gamepad y recuperación parcial.
No equivale a validar el encoder OpenCV, WebRTC ni la recepción de la radio.
