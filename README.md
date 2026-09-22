# ELRS Telemetry System — Mobula8

Sistema de telemetría en tiempo real, video FPV por WebRTC, visión por
computadora (segmentación + YOLO) e inyección de comandos RC para Mobula8
con RadioMaster TX12 y protocolo ELRS.

Versión actual: **2.7.1** — ver `CHANGELOG.md`.

La revisión inicial de Debian 13 encontró un MP4 vacío. La versión 2.7.1
corrige el formato usado por captura/grabación y añade presets NTSC y estado
real en la interfaz. Verificación con video sintético completada; validación
con gafas/capturadora reales pendiente. El control RC sigue sin validación
física y conserva los bloqueos descritos en la revisión.

| Documento | Contenido |
|-----------|-----------|
| `docs/ARCHITECTURE.md` | Resumen arquitectónico: módulos, librerías y su propósito, flujo de datos — **empezar aquí si eres nuevo en el proyecto** |
| `docs/SETUP.md` | Instalación del entorno (conda, CPU/GPU) |
| `docs/VISION_PIPELINE.md` | Pipeline de visión: cascada segmentación + YOLO, latencias y política del governor |
| `docs/YOLO_FINETUNING.md` | Guía de fine-tuning: reducir tamaño y latencia del modelo |
| `docs/RC_INJECTION.md` | Inyección de comandos RC (Fase 3): diseño, deadman y validación de protocolo |
| `docs/PLAN_ACCION.md` | Pendientes priorizados, dependencias y criterios de cierre para video y control Linux |
| `docs/PLAN_MVP_1_2_SEMANAS.md` | Plan de desarrollo y criterios de terminado para cerrar el MVP en 1–2 semanas |
| `docs/REVISION_DEBIAN13.md` | Revisión del 2026-09-21: evidencia de video vacío, diagnóstico NTSC y plan de pruebas Linux/video/control |
| `docs/HARDWARE_VALIDATION.md` | Checklist de validación manual con hardware real |
| `docs/ROADMAP.md` | Trabajo futuro y fases pendientes |
| `docs/AGENT_HANDOFF.md` | Reglas de mantenimiento de la documentación |
| `CHANGELOG.md` | Historial de cambios |

---

## 🎯 Descripción del Proyecto

Este sistema captura, visualiza y almacena la telemetría del drone Mobula8 en
tiempo real a través de conexión USB serial desde el RadioMaster TX12
(EdgeTX), y recibe el video FPV mediante una capturadora USB (EasyCap)
transmitiéndolo al navegador por WebRTC. Proporciona una interfaz web completa
accesible desde cualquier dispositivo en la red local.

### Qué hace
- **Captura telemetría CRSF** directamente desde el control remoto via USB
- **Visualiza en tiempo real**: horizonte artificial, batería, señal RF, modos de vuelo
- **Video FPV en el navegador**: stream WebRTC de baja latencia desde la capturadora USB
- **Visión por computadora**: cascada opcional de segmentación + detección
  YOLO sobre el feed FPV, con etapas que se encienden/apagan por separado.
  La inferencia corre desacoplada del stream (el video no pierde FPS) y el
  overlay muestra detecciones, latencia por etapa y la velocidad máxima
  recomendada que calcula el `LatencyGovernor`
- **Grabación MP4** asociada al `session_id` de telemetría (frame
  limpio, sin overlay — apta para post-proceso y para datasets de fine-tuning)
- **Inyección de comandos RC (Fase 3)**: frames CRSF RC Channels hacia la
  TX12 por el mismo USB, con deadman switch (>500 ms sin comandos →
  throttle al mínimo) y panel de control manual con sliders o gamepad.
  ⚠ Pendiente de validar con hardware que EdgeTX acepte CRSF entrante
  (ver `docs/RC_INJECTION.md`)
- **Registra automáticamente** cada sesión de vuelo en formato JSON
- **Explorador de vuelos**: revive cualquier vuelo con gráficas y playback del horizonte
- **Calibración de video**: herramienta standalone para brillo/contraste/gamma/balance de blancos

### Stack técnico
- **Backend**: Python 3.11 / FastAPI (lifespan) / WebSocket / pySerial
- **Video**: OpenCV (captura Windows MSMF/DSHOW; Linux V4L2/CAP_ANY) + aiortc (WebRTC) + PyAV
- **Visión**: ultralytics YOLOv8 — detección + segmentación (opcional)
- **Frontend**: Vanilla JavaScript (sin dependencias npm)
- **Protocolo**: CRSF sobre USB Serial (EdgeTX Telem Mirror, sync byte `0xEA`)
- **Almacenamiento**: JSON plano en disco (`logs/`), video MP4 en `logs/video/`

El detalle de cada librería y su propósito está en `docs/ARCHITECTURE.md`.

---

## 🏗️ Arquitectura

```
backend/                     ← Código Python
├── elrs_backend.py          ← Servidor principal (FastAPI, EJECUTAR ESTE)
├── session_manager.py       ← Gestión de sesiones de vuelo (JSON)
├── video_streamer.py        ← Captura USB + WebRTC + grabación MP4
├── vision_pipeline.py       ← Cascada de visión + LatencyGovernor
├── yolo_processor.py        ← Etapa de detección YOLO
├── segmentation_processor.py← Etapa de segmentación (opcional, previa a YOLO)
├── command_injector.py      ← Inyección RC (CRSF 0x16 + deadman, Fase 3)
├── video_calibrate.py       ← Herramienta standalone de calibración de imagen
└── video_config.json        ← Configuración de imagen (brillo, WB, etc.)
frontend/                    ← UI web (vanilla JS, sin build)
├── index.html               ← UI en tiempo real (telemetría + video + panel AI)
├── logs.html                ← Explorador de sesiones
├── css/main.css
└── js/
    ├── app.js
    ├── config.js
    └── modules/
        ├── HorizonCanvas.js      ← Horizonte artificial (Canvas 2D)
        ├── TelemetryManager.js   ← Estado reactivo
        ├── PerformanceMonitor.js ← Monitor de latencia (F2)
        ├── VideoPlayer.js        ← Cliente WebRTC (señalización + reconexión)
        └── Utils.js
docs/                        ← ARCHITECTURE, SETUP, VISION_PIPELINE,
                               YOLO_FINETUNING, ROADMAP, AGENT_HANDOFF,
                               REVISION_DEBIAN13, PLAN_ACCION
├── tests/                   ← Regresiones de video/API y cliente JS
models/                      ← Modelos .pt/.onnx propios (se crea automático)
logs/
├── session_YYYYMMDD_HHMMSS.json ← Sesiones guardadas
└── video/                        ← Grabaciones MP4
```

Pipeline de video: `captura (OpenCV) → correcciones (WB/gamma) → overlay de
visión → WebRTC (aiortc) / grabación MP4`. La inferencia
(`[segmentación] → [YOLO]`) corre en un loop desacoplado que publica
resultados; el stream solo dibuja el último publicado. Diagramas completos
en `docs/ARCHITECTURE.md` y `docs/VISION_PIPELINE.md`.

---

## 🚀 Instalación y Ejecución

Ver `docs/SETUP.md` para la guía completa con conda (Python 3.11, CPU y GPU).

### Requisitos

- Python 3.11 (recomendado; mínimo 3.8 para telemetría sin video)
- RadioMaster con EdgeTX
- Mobula8 con receptor ELRS
- Capturadora de video USB (EasyCap o similar) para el FPV
- Cable USB (datos, no solo carga)
- Navegador moderno (Chrome 90+, Firefox 88+)

### 1. Instalar dependencias Python

```bash
pip install -r requirements.txt        # servidor, telemetría y video
pip install -r requirements-yolo.txt   # opcional: pipeline de visión
```

Para GPU con CUDA, instalar torch antes de `requirements-yolo.txt`
(instrucciones dentro del propio archivo y en `docs/SETUP.md`).

### 2. Configurar EdgeTX (RadioMaster TX12)

En el control:
```
SYSTEM → USB → USB Serial (Debug)
```

Conectar el cable USB al PC.

### 3. Identificar el puerto serial

**Windows:**
```bash
python -m serial.tools.list_ports
# Buscar el puerto COM (ej: COM6)
```

**Linux:**
```bash
python -m serial.tools.list_ports -v
ls -l /dev/serial/by-id/
# Puede aparecer como ttyACM* o ttyUSB*; usar la ruta real detectada.
```

### 4. Ejecutar el servidor

Puedes arrancar sin `--port` y seleccionar **Puerto del control** en el
frontend. **Actualizar puertos** enumera los dispositivos, **Conectar /
cambiar** cambia la radio sin reiniciar y **Desconectar** cancela también
los reintentos. Windows usa COM; Linux prefiere `/dev/serial/by-id` cuando
está disponible. Una reconexión automática recupera telemetría, dejando RC
deshabilitado hasta habilitarlo expresamente.

```bash
python backend/elrs_backend.py --port COM6 --baud 115200
```

Salida esperada:
```
[VIDEO] Módulo de video cargado correctamente
ELRS Telemetry Server v2.7.1 | COM6@115200 | http://localhost:8080
[SESSION] Nueva sesión: 20260711_180000
[SESSION] Logs en: A:\...\logs
[SERIAL] Conectado a COM6 @ 115200 baud
[SERVER] ELRS Telemetry Server v2.7.1 listo
```

Si faltan las dependencias de video, el servidor arranca igual con el módulo
de video desactivado (solo telemetría).

### 5. Abrir la interfaz web

| URL | Descripción |
|-----|-------------|
| `http://localhost:8080` | Vista en tiempo real (telemetría + FPV) |
| `http://localhost:8080/logs.html` | Explorador de sesiones |
| `http://localhost:8080/docs` | API interactiva (Swagger) |
| `http://localhost:8080/api/status` | Estado del sistema |

### 6. Acceso desde otros dispositivos (tablet, teléfono)

```bash
# Ejecutar con host 0.0.0.0
python backend/elrs_backend.py --port COM6 --host 0.0.0.0
```

Luego acceder desde cualquier dispositivo en la misma red:
```
http://192.168.X.X:8080
```

---

## 📹 Video FPV y calibración

Hay dos presets: **Digital · adaptable hasta 1080p** (predeterminado, para
webcam/capturadora HD) y **Analógico · NTSC / PAL** (720×480/29.97 o
720×576/25, para Cobra X/EasyCap). Digital negocia modos de captura y
conserva el mejor formato recibido hasta 1080p; no hereda la calibración
analógica. Si el dispositivo entrega otro modo, la UI lo muestra junto
con los FPS nominales, medidos y las dimensiones recibidas en el navegador.

El selector **Vista 4:3 / Vista 16:9 / Proporción nativa** ajusta la
presentación sin recortar ni alterar las dimensiones capturadas/grabadas.
Analógico arranca en 4:3; Digital usa la proporción del frame real. Solicitar
NTSC/PAL no cambia por sí solo el estándar analógico del driver V4L2.

Cada toma usa un nombre único `video_{session_id}_{toma}.mp4` (AVI si el
encoder MP4 no abre). La UI muestra errores y la ruta del archivo al cerrar;
no hay descarga desde navegador. Stop Stream y cierre normal del servidor
finalizan el writer. Cambiar dispositivo/formato durante grabación se
rechaza. El ID asocia la toma a telemetría, sin timestamps por frame.

En la UI: seleccionar dispositivo y preset en la barra de controles del
player, **▶ Start** para iniciar el stream, **⏺ Record** para grabar MP4
asociado a la sesión. El botón **⚙** abre el panel de ajustes de imagen
(brightness/contrast/saturation/gamma) y el botón **AI** el panel de visión.

Para calibrar la imagen fuera del servidor (ventana OpenCV con histograma):

```bash
python backend/video_calibrate.py --device 0
```

Teclas: `B/b` brillo · `C/c` contraste · `S/s` saturación · `G/g` gamma ·
`R/r`, `E/e`, `U/u` balance de blancos por canal (R/G/B) · `T` preset cálido ·
`Y` neutro · `I` **anti-magenta** (recomendado para EasyCap: `wb_r 0.75,
wb_g 1.10, wb_b 0.75`) · `H` ecualización de histograma · `N` NTSC/PAL ·
`X` reset · `W` guardar en `backend/video_config.json` · `Q` salir.

El balance de blancos es por software (el driver de la EasyCap no acepta
`CAP_PROP_WB_*`) y se aplica también al stream del servidor.

---

## 🧠 Panel AI (visión por computadora)

El panel **AI** del player controla las dos etapas del pipeline de visión,
cada una con su toggle independiente:

- **DETECT** (YOLO): modelo de detección (`yolov8n/s/m` o los `.pt`/`.onnx`
  propios colocados en `models/`), slider de confidence.
- **SEGMENT**: modelo de segmentación (`yolov8n-seg` o propios con `-seg` en
  el nombre) y modo de foco: `mask` suprime el fondo antes del detector
  (cascada), `overlay` solo dibuja los contornos.

La cabecera del panel muestra en vivo: FPS de visión, detecciones, latencia
del pipeline (ms) y **Vmax** — la velocidad máxima recomendada que calcula el
`LatencyGovernor` a partir de la latencia total (más etapas encendidas →
más latencia → menor Vmax). El mismo HUD se dibuja sobre el stream. Detalles
y política completa en `docs/VISION_PIPELINE.md`; cómo entrenar y optimizar
modelos propios en `docs/YOLO_FINETUNING.md`.

La primera activación de un modelo lo descarga automáticamente (~6 MB) si no
está en `models/`.

---

## Área de detección y segmentación

En el reproductor, pulsa **Área IA** y desmarca las celdas ocupadas por las
hélices con clic o arrastre. **Aplicar** guarda la selección para ambos
modelos; **Cancelar** conserva el área anterior. **Nada** pausa la inferencia.
La grilla de 12×8 se adapta a la resolución y la proporción del video.
Consulta [el funcionamiento y la API del área de inferencia](docs/VISION_PIPELINE.md#7-grilla-de-área-de-inferencia).

## Presets de video

Selecciona **Digital · adaptable hasta 1080p** para webcam o capturadora HD,
o **Analógico · NTSC / PAL** para EasyCap/Cobra X. Digital negocia el formato
real sin aplicar la calibración analógica; la vista usa proporción nativa.
Cambiar puerto/preset reinicia el stream, excepto durante una grabación.
Ver [diagnóstico, API y validación de presets](docs/VIDEO_PRESETS.md).

## 🎮 Panel RC (inyección de comandos — Fase 3)

El botón **RC** del player abre el panel de control manual: sliders
THROTTLE/ROLL/PITCH/YAW (µs 988–2012), botón **Center** (posición segura) y
soporte de **gamepad** (Web Gamepad API, Mode 2: stick izquierdo
throttle/yaw, derecho roll/pitch). Al habilitarlo, la UI envía los canales
a 10 Hz por `WS /ws/rc` y el backend los retransmite como frames CRSF a
50 Hz hacia la TX12.

Seguridad integrada:

- **Deadman switch**: si el backend deja de recibir comandos >500 ms
  (pestaña cerrada, red caída), los canales caen a failsafe — throttle al
  mínimo, ejes centrados, aux abajo. El badge del panel muestra el estado
  en vivo: `OFF` / `FAILSAFE` / `LIVE`.
- Habilitar la inyección requiere el serial de la TX12 conectado (409 si no).
- Al habilitar siempre se arranca en failsafe, nunca con valores viejos.

⚠ **Pendiente de validación de protocolo**: no está confirmado que EdgeTX
acepte CRSF entrante por USB en modo Telem Mirror. Plan de pruebas en
`docs/HARDWARE_VALIDATION.md` §4b y diseño completo en
`docs/RC_INJECTION.md`. La pérdida de gamepad, del propietario WebSocket o de serial revoca
el control. Tras un timeout se requiere adquirir una nueva época con los
16 canales y throttle mínimo; la UI lo hace al volver a habilitar RC.
El transporte PC → TX12 sigue pendiente de validación de banco, con el
drone desarmado y sin hélices.

---

## 📡 Configuración ELRS/Betaflight

Para obtener telemetría fluida (≥10 fps):

### Betaflight CLI (copiar y pegar)
```
set msp_override_channels_rate = 50
set msp_override_msp_rate = 100
save
```

### EdgeTX — Telemetría
```
SYSTEM → RADIO SETUP → Telemetry refresh: Fast (50ms)
MDL → TELEMETRY → Discover new sensors
```

### ELRS Telemetry Ratio
- Para uso estacionario con USB: `1:8` (31 fps, recomendado)
- Para vuelo en campo: `1:16` (15 fps, buen alcance)

---

## 🗂️ Formato de sesiones JSON

Cada sesión guardada en `logs/session_YYYYMMDD_HHMMSS.json`:

```json
{
  "session_id": "20260503_180000",
  "start_time": "2026-05-03T18:00:00+00:00",
  "end_time":   "2026-05-03T18:05:30+00:00",
  "summary": {
    "total_frames":    820,
    "duration_seconds": 330,
    "max_voltage":     7.4,
    "min_voltage":     6.8,
    "avg_voltage":     7.1,
    "max_current":     8.2,
    "total_mah":       485,
    "min_battery_pct": 28,
    "avg_rssi":       -68.5,
    "min_rssi":       -92.0,
    "avg_lq":          97.2,
    "min_lq":          84,
    "max_pitch":       22.1,
    "max_roll":        35.4,
    "flight_modes":   ["DISARMED", "STAB"],
    "frame_counts":   {"link": 400, "battery": 200, "attitude": 200, "flight_mode": 20}
  },
  "frames": [
    {"timestamp": "2026-05-03T18:00:00.012Z", "type": "link",    "data": {...}},
    {"timestamp": "2026-05-03T18:00:00.062Z", "type": "battery", "data": {...}},
    {"timestamp": "2026-05-03T18:00:00.112Z", "type": "attitude","data": {...}}
  ]
}
```

---

## 🌐 API Endpoints

### Telemetría y sesiones

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `WS` | `/ws` | Telemetría en tiempo real |
| `GET` | `/api/status` | Estado del servidor y sesión activa |
| `GET` | `/api/history?limit=100` | Últimos N frames en memoria |
| `GET` | `/api/latest` | Último frame de cada tipo |
| `GET` | `/api/sessions` | Lista de sesiones guardadas |
| `GET` | `/api/sessions/{id}` | Datos completos de una sesión |
| `GET` | `/api/sessions/{id}/summary` | Solo resumen (sin frames) |
| `DELETE` | `/api/sessions/{id}` | Eliminar sesión |
| `POST` | `/api/sessions/save` | Guardar sesión actual y crear nueva |

### Video FPV (WebRTC)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/video/devices` | Lista capturadoras disponibles |
| `GET` | `/api/video/status` | Estado del stream, grabación y visión |
| `GET` | `/api/video/config` | Configuración de imagen actual |
| `POST` | `/api/video/config` | Actualiza `backend/video_config.json` y aplica al vuelo |
| `POST` | `/api/video/start` | Solicitar captura (FPS decimales); devuelve formato real, pedido y advertencias |
| `POST` | `/api/video/stop` | Detener captura |
| `POST` | `/api/video/recording/start` | Grabar MP4 asociado a la sesión |
| `POST` | `/api/video/recording/stop` | Detener grabación |
| `POST` | `/offer` | Señalización WebRTC (SDP offer → answer) |

### Visión (segmentación + YOLO + governor)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/vision/status` | Estado completo: etapas, latencias por etapa, FPS de visión, governor |
| `GET` | `/api/vision/models` | Modelos disponibles por etapa (defaults + `models/`) |
| `POST` | `/api/segmentation/config` | Etapa de segmentación: `enabled`, `model`, `confidence`, `focus_mode` (`mask`/`overlay`), `imgsz` |
| `POST` | `/api/yolo/config` | Etapa de detección: `enabled`, `model`, `confidence`, `imgsz` |
| `POST` | `/api/vision/governor` | Política de latencia: `safety_distance_m`, `reaction_time_ms` |
| `GET` | `/api/yolo/status` | Estado del detector (compatibilidad) |
| `GET` | `/api/yolo/models` | Modelos de detección (compatibilidad) |

### Inyección RC (Fase 3)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/rc/status` | Estado: enabled, deadman/failsafe, canales, frames enviados |
| `POST` | `/api/rc/config` | `enabled`, `rate_hz`, `deadman_ms`, `sync_byte` (409 sin serial) |
| `POST` | `/api/rc/acquire` | Estado completo de 16 canales y throttle=988; devuelve `epoch` |
| `POST` | `/api/rc/channels` | `epoch` y estado completo de 16 canales; alias AETR o índice 1–16, µs |
| `POST` | `/api/rc/center` | Todos los canales a failsafe (posición segura) |
| `WS` | `/ws/rc` | Canal continuo de baja latencia (UI/gamepad, 10 Hz) |

---

## ⌨️ Atajos de teclado

| Tecla | Acción |
|-------|--------|
| `F2` | Toggle performance monitor (FPS, latencia, update rate) |

---

## Pruebas de software

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
node tests/test_video_player.mjs
```

Las pruebas usan imágenes sintéticas, API ASGI y escritura/decodificación
OpenCV real; no requieren radio ni capturadora. La aceptación con hardware
se describe en `docs/PLAN_ACCION.md`.

## 🛠️ Troubleshooting

### "Serial port not found"
```bash
python -m serial.tools.list_ports
# Usar el puerto correcto: --port COM5
```

### Horizonte con lag (>500ms)
1. Verificar Telemetry Ratio en ELRS (debe ser 1:16 o menor)
2. Ejecutar en Betaflight CLI: `set msp_override_msp_rate = 100`
3. En EdgeTX: Telemetry refresh = Fast

### Frontend no carga
- Verificar que `frontend/` está en la raíz del repo (el backend lo resuelve
  desde `backend/` con ruta relativa)
- Abrir `http://localhost:8080` (no `file://`)

### El stream FPV falla al cargar la página (404 / MIME error en consola)
- `index.html` importa `./js/modules/VideoPlayer.js`. Verificar que el
  archivo existe en `frontend/js/modules/`. Este bug reapareció en varias
  sesiones cuando el archivo se generaba en la ubicación equivocada.

### La capturadora no aparece en la lista de dispositivos
- Las EasyCap se registran en Windows bajo la clase PnP `Media` o `Image`,
  no `Camera`. Desde v2.4.1 la enumeración usa `Win32_PnPEntity` con las
  tres clases, y abre por índice con `CAP_MSMF` primero (OpenCV 4.8+).
- Probar la capturadora directamente: `python backend/video_streamer.py --device 0`

### Imagen con tinte violeta/magenta (EasyCap)
- El driver no corrige el balance de blancos. Ejecutar
  `python backend/video_calibrate.py` y presionar `I` (preset anti-magenta),
  ajustar con `R/E/U` si hace falta, y `W` para guardar. El servidor aplica
  la corrección por software en cada frame.

### El servidor no arranca tras tocar el módulo de video
- Desde v2.4.1 cualquier excepción al cargar `video_streamer.py` solo
  desactiva el video (mensaje `[VIDEO] Módulo no disponible`), no tumba el
  servidor. Si aparece ese mensaje, revisar el traceback impreso y las
  dependencias: `pip install -r requirements.txt`.

### Las anotaciones de visión van "atrasadas" respecto al video
- Es el diseño (v2.6.0): la inferencia corre desacoplada y el stream dibuja
  el último resultado publicado, así el video no pierde FPS. El desfase
  máximo es un ciclo de inferencia (visible en el HUD). Si molesta, reducir
  la latencia del modelo: `imgsz` 416/320, apagar la segmentación, o un
  modelo optimizado (`docs/YOLO_FINETUNING.md`).

### Existe un MP4 pero no se reproduce
- Comprobar `ffprobe -v error -show_streams -show_format ARCHIVO.mp4`.
  La prueba inicial de Debian 13 dejó 258 bytes sin pistas; ese archivo
  antiguo no se recupera con el cambio de código.
- Desde 2.7.1 el writer recibe la geometría real y se cierra al detener
  captura/servidor. Las nuevas tomas no sobrescriben las anteriores.
- Revisar el error visible y validar un archivo nuevo con el procedimiento
  de `docs/PLAN_ACCION.md`. Un contador de frames no acredita persistencia.

### La inyección RC no mueve nada en la TX12
- Es la incógnita de protocolo abierta de Fase 3: EdgeTX podría no aceptar
  CRSF entrante por USB en modo Telem Mirror. Probar las tres direcciones
  con `sync_byte` (`0xEE`/`0xEA`/`0xC8`) siguiendo
  `docs/HARDWARE_VALIDATION.md` §4b y registrar el resultado en
  `docs/RC_INJECTION.md` §3 (ahí está también el plan B).
- Verificar primero lo local: `GET /api/rc/status` debe mostrar
  `serial_connected: true`, `enabled: true` y `frames_sent` creciendo.

### El panel RC queda en "FAILSAFE"
- El deadman no está recibiendo comandos frescos (>500 ms). Con el panel
  abierto y habilitado la UI envía a 10 Hz — si aún así queda en FAILSAFE,
  revisar la consola del navegador (¿WebSocket `/ws/rc` cerrado?) y que no
  haya un proxy bloqueando WebSockets.

### El panel AI muestra "Vmax HOVER" (modo stale)
- La inferencia no está publicando resultados frescos (>1.5 s). Causas
  típicas: modelo demasiado pesado para la CPU (usar yolov8n, bajar
  `imgsz`), o la captura se detuvo. Ver `latency.vision_fps` en
  `GET /api/vision/status`.

---

## 📁 Estructura de archivos

```
.
├── backend/                 ← Código Python
│   ├── elrs_backend.py      ← Servidor principal (EJECUTAR ESTE)
│   ├── session_manager.py   ← Módulo de sesiones (no ejecutar solo)
│   ├── video_streamer.py    ← Video FPV: captura + WebRTC + grabación
│   ├── vision_pipeline.py   ← Cascada de visión + LatencyGovernor
│   ├── yolo_processor.py    ← Etapa de detección YOLO
│   ├── segmentation_processor.py ← Etapa de segmentación (opcional)
│   ├── command_injector.py  ← Inyección RC + deadman (Fase 3)
│   ├── video_calibrate.py   ← Calibración de imagen (standalone)
│   └── video_config.json    ← Config de imagen generada por la calibración
├── frontend/                ← Interfaz web (servida por el backend)
│   ├── index.html
│   ├── logs.html
│   ├── css/
│   └── js/
│       └── modules/         ← Incluye VideoPlayer.js (cliente WebRTC)
├── docs/
│   ├── ARCHITECTURE.md      ← Resumen arquitectónico y librerías (onboarding)
│   ├── SETUP.md             ← Guía de instalación con conda (CPU/GPU)
│   ├── VISION_PIPELINE.md   ← Pipeline de visión y política de latencia
│   ├── YOLO_FINETUNING.md   ← Guía de fine-tuning (tamaño y latencia)
│   ├── RC_INJECTION.md      ← Inyección RC: diseño, deadman, protocolo
│   ├── HARDWARE_VALIDATION.md ← Checklist de validación con hardware real
│   ├── REVISION_DEBIAN13.md  ← Diagnóstico inicial Linux/NTSC/RC
│   ├── PLAN_ACCION.md        ← Estado de pendientes y criterios de cierre
│   ├── PLAN_MVP_1_2_SEMANAS.md ← Plan de cierre del MVP en 1–2 semanas
│   ├── ROADMAP.md           ← Trabajo futuro (no mezclar con este README)
│   └── AGENT_HANDOFF.md     ← Reglas de mantenimiento de la documentación
├── models/                  ← Modelos YOLO .pt/.onnx (se crea automático, fuera de git)
├── logs/                    ← Sesiones guardadas (se crea automático, fuera de git)
│   ├── session_*.json
│   └── video/               ← Grabaciones MP4
├── tests/                   ← Regresiones de captura, grabación, API y cliente JS
├── requirements-test.txt    ← Dependencias de pruebas (incluye core)
├── requirements.txt         ← Dependencias core
├── requirements-yolo.txt    ← Dependencias opcionales de visión
├── .gitignore
├── CHANGELOG.md             ← Historial de cambios
└── README.md
```
