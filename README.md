# ELRS Telemetry System — Mobula8

Sistema de telemetría en tiempo real, video FPV por WebRTC y visión por
computadora (YOLO) para Mobula8 con RadioMaster TX12 y protocolo ELRS.

Versión actual: **2.4.1** — ver `CHANGELOG.md`. El trabajo futuro vive en
`ROADMAP.md`; las reglas de mantenimiento de estos documentos, en
`AGENT_HANDOFF.md`.

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
- **Detección de objetos (YOLO)**: inferencia YOLOv8 opcional sobre el feed FPV, con panel AI en la UI
- **Grabación MP4** sincronizada con el `session_id` de telemetría
- **Registra automáticamente** cada sesión de vuelo en formato JSON
- **Explorador de vuelos**: revive cualquier vuelo con gráficas y playback del horizonte
- **Calibración de video**: herramienta standalone para brillo/contraste/gamma/balance de blancos

### Stack técnico
- **Backend**: Python 3.11 / FastAPI (lifespan) / WebSocket / pySerial
- **Video**: OpenCV (captura MSMF/DSHOW) + aiortc (WebRTC) + PyAV
- **Visión**: ultralytics YOLOv8 (opcional)
- **Frontend**: Vanilla JavaScript (sin dependencias npm)
- **Protocolo**: CRSF sobre USB Serial (EdgeTX Telem Mirror, sync byte `0xEA`)
- **Almacenamiento**: JSON plano en disco (`logs/`), video MP4 en `logs/video/`

---

## 🏗️ Arquitectura

```
elrs_backend.py          ← Servidor principal (FastAPI, EJECUTAR ESTE)
session_manager.py       ← Gestión de sesiones de vuelo (JSON)
video_streamer.py        ← Captura USB + WebRTC + grabación MP4
yolo_processor.py        ← Inferencia YOLOv8 sobre el pipeline de video
video_calibrate.py       ← Herramienta standalone de calibración de imagen
video_config.json        ← Configuración de imagen (brillo, WB, etc.)
frontend-vanilla/
├── index.html           ← UI en tiempo real (telemetría + video + panel AI)
├── logs.html            ← Explorador de sesiones
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
models/                  ← Modelos .pt personalizados (se crea automático)
logs/
├── session_YYYYMMDD_HHMMSS.json ← Sesiones guardadas
└── video/                        ← Grabaciones MP4
```

Pipeline de video: `captura (OpenCV) → correcciones (WB/gamma) → [YOLO si
está activo] → WebRTC (aiortc) / grabación MP4`.

---

## 🚀 Instalación y Ejecución

Ver `SETUP.md` para la guía completa con conda (Python 3.11, CPU y GPU).

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
pip install -r requirements-yolo.txt   # opcional: pipeline YOLO
```

Para GPU con CUDA, instalar torch antes de `requirements-yolo.txt`
(instrucciones dentro del propio archivo y en `SETUP.md`).

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
ls /dev/ttyUSB*
# Normalmente /dev/ttyUSB0
```

### 4. Ejecutar el servidor

```bash
python elrs_backend.py --port COM6 --baud 115200
```

Salida esperada:
```
[VIDEO] Módulo de video cargado correctamente
ELRS Telemetry Server v2.4.1 | COM6@115200 | http://localhost:8080
[SESSION] Nueva sesión: 20260710_180000
[SESSION] Logs en: A:\...\logs
[SERIAL] Conectado a COM6 @ 115200 baud
[SERVER] ELRS Telemetry Server v2.4.1 listo
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
python elrs_backend.py --port COM6 --host 0.0.0.0
```

Luego acceder desde cualquier dispositivo en la misma red:
```
http://192.168.X.X:8080
```

---

## 📹 Video FPV y calibración

En la UI: seleccionar dispositivo y resolución en la barra de controles del
player, **▶ Start** para iniciar el stream, **⏺ Record** para grabar MP4
sincronizado con la sesión. El botón **⚙** abre el panel de ajustes de imagen
(brightness/contrast/saturation/gamma) y el botón **AI** el panel YOLO
(modelo, confidence, toggle).

Para calibrar la imagen fuera del servidor (ventana OpenCV con histograma):

```bash
python video_calibrate.py --device 0
```

Teclas: `B/b` brillo · `C/c` contraste · `S/s` saturación · `G/g` gamma ·
`R/r`, `E/e`, `U/u` balance de blancos por canal (R/G/B) · `T` preset cálido ·
`Y` neutro · `I` **anti-magenta** (recomendado para EasyCap: `wb_r 0.75,
wb_g 1.10, wb_b 0.75`) · `H` ecualización de histograma · `N` NTSC/PAL ·
`X` reset · `W` guardar en `video_config.json` · `Q` salir.

El balance de blancos es por software (el driver de la EasyCap no acepta
`CAP_PROP_WB_*`) y se aplica también al stream del servidor.

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
| `GET` | `/api/video/status` | Estado del stream y grabación |
| `GET` | `/api/video/config` | Configuración de imagen actual |
| `POST` | `/api/video/config` | Actualiza `video_config.json` y aplica al vuelo |
| `POST` | `/api/video/start` | Iniciar captura (`device_id`, `width`, `height`, `fps`) |
| `POST` | `/api/video/stop` | Detener captura |
| `POST` | `/api/video/recording/start` | Grabar MP4 sincronizado con la sesión |
| `POST` | `/api/video/recording/stop` | Detener grabación |
| `POST` | `/offer` | Señalización WebRTC (SDP offer → answer) |

### Visión (YOLO)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/yolo/status` | Estado del procesador (FPS de inferencia, detecciones, modelo) |
| `GET` | `/api/yolo/models` | Modelos default + archivos `.pt` en `models/` |
| `POST` | `/api/yolo/config` | Activa/desactiva YOLO, cambia modelo, ajusta confidence |

---

## ⌨️ Atajos de teclado

| Tecla | Acción |
|-------|--------|
| `F2` | Toggle performance monitor (FPS, latencia, update rate) |

---

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
- Verificar que `frontend-vanilla/` está junto a `elrs_backend.py`
- Abrir `http://localhost:8080` (no `file://`)

### El stream FPV falla al cargar la página (404 / MIME error en consola)
- `index.html` importa `./js/modules/VideoPlayer.js`. Verificar que el
  archivo existe en `frontend-vanilla/js/modules/` — **no** en la raíz del
  proyecto. Este bug reapareció en varias sesiones cuando el archivo se
  generaba en la ubicación equivocada.

### La capturadora no aparece en la lista de dispositivos
- Las EasyCap se registran en Windows bajo la clase PnP `Media` o `Image`,
  no `Camera`. Desde v2.4.1 la enumeración usa `Win32_PnPEntity` con las
  tres clases, y abre por índice con `CAP_MSMF` primero (OpenCV 4.8+).
- Probar la capturadora directamente: `python video_streamer.py --device 0`

### Imagen con tinte violeta/magenta (EasyCap)
- El driver no corrige el balance de blancos. Ejecutar
  `python video_calibrate.py` y presionar `I` (preset anti-magenta), ajustar
  con `R/E/U` si hace falta, y `W` para guardar. El servidor aplica la
  corrección por software en cada frame.

### El servidor no arranca tras tocar el módulo de video
- Desde v2.4.1 cualquier excepción al cargar `video_streamer.py` solo
  desactiva el video (mensaje `[VIDEO] Módulo no disponible`), no tumba el
  servidor. Si aparece ese mensaje, revisar el traceback impreso y las
  dependencias: `pip install -r requirements.txt`.

---

## 📁 Estructura de archivos

```
.
├── elrs_backend.py          ← Servidor principal (EJECUTAR ESTE)
├── session_manager.py       ← Módulo de sesiones (no ejecutar solo)
├── video_streamer.py        ← Video FPV: captura + WebRTC + grabación
├── yolo_processor.py        ← Inferencia YOLO (opcional)
├── video_calibrate.py       ← Calibración de imagen (standalone)
├── video_config.json        ← Config de imagen generada por la calibración
├── requirements.txt         ← Dependencias core
├── requirements-yolo.txt    ← Dependencias opcionales de visión
├── frontend-vanilla/        ← Interfaz web (servida por el backend)
│   ├── index.html
│   ├── logs.html
│   ├── css/
│   └── js/
│       └── modules/         ← Incluye VideoPlayer.js (cliente WebRTC)
├── models/                  ← Modelos YOLO .pt (se crea automático)
├── logs/                    ← Sesiones guardadas (se crea automático)
│   ├── session_*.json
│   └── video/               ← Grabaciones MP4
├── SETUP.md                 ← Guía de instalación con conda (CPU/GPU)
├── CHANGELOG.md             ← Historial de cambios
├── ROADMAP.md               ← Trabajo futuro (no mezclar con este README)
├── AGENT_HANDOFF.md         ← Reglas de mantenimiento de la documentación
└── README.md
```
