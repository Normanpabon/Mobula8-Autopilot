> Las fases pendientes (Fase 3 — inyección EdgeTX, Fase 4 — vuelo autónomo)
> y el resto del trabajo futuro viven ahora en `docs/ROADMAP.md`.

## [2.5.0] — 2026-07-10

### Cambiado — Reestructuración del repositorio

- **Separación por responsabilidades en carpetas** (todos los movimientos
  con `git mv`, el historial se preserva):
  - `backend/` — todo el código Python (`elrs_backend.py`,
    `session_manager.py`, `video_streamer.py`, `yolo_processor.py`,
    `video_calibrate.py`) más `video_config.json`.
  - `frontend/` — la UI web (renombrada desde `frontend-vanilla/`; los
    imports internos son relativos, no cambió nada dentro).
  - `docs/` — `SETUP.md`, `ROADMAP.md`, `AGENT_HANDOFF.md` y el nuevo
    `ARCHITECTURE.md`. `README.md` y `CHANGELOG.md` quedan en la raíz.
- **Nuevo comando de arranque**: `python backend/elrs_backend.py`
  (antes `python elrs_backend.py`).
- Rutas internas ajustadas: los módulos de `backend/` resuelven la raíz del
  repo con `Path(__file__).resolve().parent.parent` para `logs/`, `models/`
  y `frontend/`; `video_config.json` se queda junto al código en `backend/`.

### Añadido

- **`docs/ARCHITECTURE.md`**: resumen arquitectónico para onboarding —
  diagrama de flujo de datos, responsabilidad de cada módulo (backend y
  frontend), tabla de librerías con su propósito, protocolos (CRSF/WS/
  WebRTC/REST), presupuesto de latencia y decisiones de diseño.
- **`.gitignore`**: `__pycache__/` eliminado del tracking de git (los `.pyc`
  se "modificaban" en cada ejecución); `logs/` y `models/` también ignorados.

### Verificación

- `py_compile` de los cinco módulos, `import` del backend desde la nueva
  estructura: versión 2.5.0, `frontend/` resuelto, `logs/` y `models/`
  apuntando a la raíz, 12 rutas de video/YOLO/`offer` registradas.
- Pendiente (sin cambios): validación en runtime con hardware real.

---

## [2.4.1] — 2026-07-10

### Corregido
- **`frontend-vanilla/index.html`**: el flag `streaming` no se sincronizaba con el
  estado real del `VideoPlayer`. Tras un error de conexión quedaba en `true` y el
  botón "Retry" ejecutaba `disconnect()` en vez de reconectar. Ahora `streaming`
  se deriva de `state` dentro de `updateVideoUI()`.
- **`frontend-vanilla/js/modules/VideoPlayer.js`**: `connect()` no cancelaba un
  timer de reconexión pendiente. Pulsar "Retry" durante el backoff automático
  podía abrir dos `RTCPeerConnection` simultáneas. Ahora `connect()` limpia el
  timer al inicio, y el contador de reintentos se resetea en `disconnect()`.

### Cambiado
- **`elrs_backend.py`** migrado de `@app.on_event("startup"/"shutdown")`
  (deprecated en FastAPI) al patrón `lifespan` con `@asynccontextmanager`.
- **CRC8 DVB-S2**: la tabla se precomputa una sola vez al importar el módulo
  (antes se reconstruía en cada frame CRSF recibido, cientos de veces/segundo).
- El bloque de carga del módulo de video captura `Exception` genérico (no solo
  `ImportError`): un fallo de carga en `video_streamer.py` desactiva el módulo
  de video en vez de tumbar el servidor completo.
- **Enumeración/apertura de capturadoras**: se prueba `cv2.CAP_MSMF` antes que
  `cv2.CAP_DSHOW` en Windows (OpenCV 4.8+ abre por índice con más fiabilidad
  por MSMF). Aplica a `video_streamer.py` y `video_calibrate.py`, manteniendo
  el mismo mapeo de índices entre ambos.
- **Nombres de dispositivo** via `Get-CimInstance Win32_PnPEntity` filtrando
  `PNPClass -in @('Camera','Image','Media')`, en vez de `Get-PnpDevice -Class Camera`
  (las EasyCap no siempre se registran bajo la clase Camera).
- Versión del servidor unificada a **2.4.1** (el constructor de `FastAPI(...)`
  declaraba `2.0.0` desde hacía varias versiones).

### Notas de reconciliación
- La sesión del 2026-07-10 trabajó sobre un **snapshot antiguo** del proyecto
  (~v2.3.0) sin los commits de mayo. Sus "fixes críticos" (imports de aiortc,
  rutas registradas después de `uvicorn.run()`) correspondían a bugs de ese
  snapshot que **ya estaban resueltos** en el repo desde v2.3.1/v2.4.0, y sus
  versiones de los `.py` eliminaban toda la integración YOLO. Se descartaron
  esos archivos y se portaron a la base v2.4.0 únicamente las mejoras listadas
  arriba. `VideoPlayer.js` e `index.html` (raíz) fueron absorbidos en
  `frontend-vanilla/` y eliminados de la raíz.
- Pendiente: **validación en runtime con hardware real** (TX12 + Mobula8 +
  EasyCap). Todo lo anterior se verificó por importación del backend
  (12 rutas de video/YOLO registradas), `py_compile` y `node --check`.

---

## [2.4.0] — 2026-05-31

### Añadido — Fase 2: Pipeline YOLO

- **`yolo_processor.py`**: módulo de inferencia de visión en tiempo real
  - `YOLOProcessor`: carga modelos YOLOv8/v11 (`.pt`) con warm-up automático
  - Inferencia asíncrona en `ThreadPoolExecutor` de 1 worker (no bloquea el event loop)
  - `process_async()`: pipeline `frame BGR → inferencia → frame anotado BGR`
  - Bounding boxes y labels dibujados con `results[0].plot()` (ultralytics nativo)
  - Busca modelos en carpeta `models/` primero; descarga automática si no existe
  - Falla silenciosamente si `ultralytics` no está instalado
  - `list_local_models()`: enumera archivos `.pt` disponibles localmente
- **`models/`**: carpeta para modelos `.pt` personalizados (creada automáticamente)
- **Refactor de pipeline de frames en `video_streamer.py`**:
  - `FPVVideoTrack` ahora recibe un `frame_getter` (callable async) en vez de `VideoCapture`
    — desacopla el track WebRTC de la fuente de frames para permitir pasos intermedios
  - `WebRTCManager` recibe `frame_getter + width/height/fps` en lugar de `VideoCapture`
  - `VideoStreamer._get_display_frame()`: pipeline `captura → [YOLO si enabled] → frame BGR`
  - `VideoStreamer` importa `YOLOProcessor` opcionalmente al iniciar
- **Nuevos endpoints API**:
  - `GET /api/yolo/status` — estado del procesador (FPS de inferencia, detecciones, modelo)
  - `GET /api/yolo/models` — lista modelos default + archivos `.pt` en `models/`
  - `POST /api/yolo/config` — activa/desactiva YOLO, cambia modelo, ajusta confidence
- **Panel AI en `index.html`**:
  - Botón **AI** en barra de controles de video
  - Panel colapsable con selector de modelo, slider de confidence (10–95%) y toggle
  - Badge `● AI` superpuesto en el video mientras YOLO está activo
  - Polling de stats cada 1.5s: FPS de inferencia y cantidad de objetos detectados
  - Carga dinámica de modelos disponibles desde `/api/yolo/models`
- **`requirements-yolo.txt`**: dependencias opcionales para YOLO (ultralytics)

### Dependencias nuevas (opcionales)
```bash
pip install -r requirements-yolo.txt
# Para GPU CUDA 12.1:
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements-yolo.txt
```

---

## [2.3.1] — 2026-05-31

### Corregido — Fase 1: Estabilización de video

- **Bug crítico de routing** en `elrs_backend.py`: las rutas `GET /api/video/devices` y
  `GET /api/video/status` eran interceptadas por el catch-all `GET /{full_path:path}` del
  frontend (registrado antes), devolviendo 404 siempre. Todos los endpoints de video API
  ahora se registran **antes** del bloque de servicio del frontend.
- **`POST /api/video/start`**: reemplazado `request: dict = None` (no funcionaba con FastAPI)
  por modelo Pydantic `VideoStartRequest` — body parsing ahora correcto.
- **`DeviceManager.enumerate()`**: reescrita para escanear índices 0–4 **en paralelo**
  con `ThreadPoolExecutor(max_workers=5)` y timeout de 12s total. Elimina el bloqueo de
  varios segundos por dispositivo que causaba que la UI no recibiera la lista de cámaras.
- **`VideoCapture.update_config()`**: nuevo método para aplicar brillo/contraste/saturación
  al vuelo sin reiniciar la captura.
- Imports duplicados eliminados en `video_streamer.py`.

### Añadido

- **Panel de configuración de video** en `index.html`:
  - Botón **⚙** en la barra de controles de video
  - Panel colapsable con sliders para Brightness, Contrast, Saturation y Gamma
  - Botón **↻ Refresh** para recargar la lista de dispositivos
  - Botón **✓ Apply** que envía `POST /api/video/config`
  - Al cargar la página sincroniza los sliders con los valores de `video_config.json`
- **`GET /api/video/config`**: devuelve la configuración actual de video
- **`POST /api/video/config`**: actualiza `video_config.json` y aplica cambios al stream
  en curso sin necesidad de reiniciar
- **`requirements.txt`**: dependencias core del proyecto con versiones mínimas
- **`SETUP.md`**: guía de instalación con conda (Python 3.11), pasos para CPU y GPU,
  workaround para `aiortc` en Windows, comandos útiles de conda

---

## [2.3.0] — 2026-05-12

### Añadido
- **video_streamer.py**: Módulo completo de captura y streaming de video FPV
  - DeviceManager: enumeración automática de capturadoras USB disponibles
  - VideoCapture: lectura de frames via OpenCV con DirectShow (baja latencia en Windows)
  - FPVVideoTrack: track de video WebRTC basado en aiortc (sin audio)
  - WebRTCManager: manejo multi-cliente peer-to-peer con RTCPeerConnection por cliente
  - VideoRecorder: grabación MP4 sincronizada con el session_id de telemetría
  - Modo standalone: `python video_streamer.py --device 0` para probar la capturadora
- **VideoPlayer.js** (`js/modules/VideoPlayer.js`): cliente WebRTC completo en el browser
  - Señalización SDP automática via POST /offer
  - Reconexión automática con backoff exponencial
  - Control de dispositivo y resolución
  - Inicio/detención de grabación sincronizada
- **Endpoints API de video** en elrs_backend.py:
  - `GET /api/video/devices` — lista capturadoras disponibles
  - `GET /api/video/status`  — estado del stream y grabación
  - `POST /api/video/start`  — iniciar captura (device_id, width, height, fps)
  - `POST /api/video/stop`   — detener captura
  - `POST /api/video/recording/start` — grabar sincronizado con sesión
  - `POST /api/video/recording/stop`  — detener grabación
  - `POST /offer`            — señalización WebRTC SDP offer/answer
- **index.html**: Reemplazo del placeholder por player WebRTC real
  - Elemento `<video>` nativo con autoplay/mute
  - Barra de controles: selector de dispositivo, resolución, start/stop stream, record
  - Indicador de estado: IDLE / CONNECTING / CONNECTED / ERROR
  - Timer de grabación en tiempo real
  - Reconexión automática al perder el stream
- **PLAN_VIDEO_WEBRTC.md**: Documento de arquitectura de la iteración de video

### Cambiado
- elrs_backend.py v3.0: carga opcional del módulo de video (falla gracefully si faltan deps)
- index.html: panel central ahora es el player WebRTC con controles completos

### Dependencias nuevas
```bash
pip install aiortc opencv-python
```

---


# Changelog — ELRS Telemetry System

Todos los cambios notables de este proyecto están documentados en este archivo.
Formato basado en [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.2.0] — 2026-05-03

### Añadido
- **SessionManager** (`session_manager.py`): Guarda automáticamente cada sesión de vuelo en JSON
  - Resumen automático: voltaje min/max/avg, corriente máx, mAh usados, RSSI, LQ, actitud máxima
  - Sesión se inicia al arrancar el servidor y se guarda al apagar con Ctrl+C
  - Soporte para guardar sesión manualmente y abrir una nueva via API
- **Explorador de logs** (`logs.html`): Interfaz web para explorar sesiones guardadas
  - Lista de sesiones con metadatos (fecha, duración, frames, tamaño)
  - Panel de estadísticas por sesión (voltaje, corriente, RSSI, etc.)
  - Gráficas de voltaje, corriente, RSSI y LQ a lo largo del tiempo (Canvas 2D)
  - Playback del horizonte artificial con scrubber y controles play/pause
  - Exportación de sesiones a JSON
  - Eliminación de sesiones desde la UI
  - Indicador de sesión LIVE en tiempo real
- **Nuevos endpoints API**:
  - `GET /api/sessions` — Lista sesiones + sesión en curso
  - `GET /api/sessions/{id}` — Datos completos de una sesión
  - `GET /api/sessions/{id}/summary` — Solo resumen (sin frames)
  - `DELETE /api/sessions/{id}` — Eliminar sesión
  - `POST /api/sessions/save` — Guardar sesión y abrir nueva
- **Botón LOGS** en header de `index.html` con navegación a `/logs.html`
- **Backend v2.0**: Integración completa del SessionManager en el serial reader

### Cambiado
- `elrs_backend.py` actualizado a v2.0 con soporte de sesiones
- `system_status` incluye ahora `current_session_id` y `current_session_frames`
- La sesión se guarda automáticamente al recibir señal de apagado (shutdown event)

---

## [2.1.0] — 2026-05-03

### Añadido
- **PerformanceMonitor** (`js/modules/PerformanceMonitor.js`):
  - Overlay de métricas en tiempo real (FPS, latencia, update rate)
  - Activar/desactivar con tecla `F2`
  - Tracking de latencia end-to-end basado en timestamps
- **Diagnóstico agresivo de latencia** (`diagnostic.js`, `immediate_fix.js`):
  - Scripts para pegar en consola del navegador
  - Identificación del cuello de botella (backend vs frontend vs WebSocket)
- **Diagnóstico de puerto serial** (`diagnostic_serial.py`):
  - Mide frames por segundo del puerto serial
  - Identifica problemas de configuración ELRS/EdgeTX

### Corregido
- **Latencia de actualización de telemetría**: Gap reducido de 2975ms a objetivo <100ms
  - Root cause: Telemetry Ratio de ELRS configurado en 1:128 (cada 512ms)
  - Solución: Cambiar a 1:16 o 1:8 + configurar EdgeTX refresh a Fast (50ms)
- `app.perfMonitor` ahora disponible en `window.app` para debugging en consola

### Cambiado
- Smooth factor del horizonte: `0.15` → `0.8` (5x más responsivo)
- `config.js`: `smoothFactor` actualizado al valor optimizado

---

## [2.0.0] — 2026-05-03

### Añadido
- **Migración completa a Vanilla JavaScript** (cero dependencias npm)
  - `index.html`: Estructura HTML5 semántica
  - `css/main.css`: Sistema de diseño con variables CSS, tema oscuro aviation
  - `js/app.js`: WebSocket manager + auto-reconnect
  - `js/modules/TelemetryManager.js`: Gestión de estado reactiva con eventos
  - `js/modules/Utils.js`: Helpers (formateo, math, Canvas utilities)
  - `js/modules/HorizonCanvas.js`: Horizonte artificial Canvas 2D a 60fps
  - `js/config.js`: Configuración centralizada y personalizable
  - `js/test.js`: Utilities de testing (simulación de vuelo, stress test)
- **HorizonCanvas** (sin Three.js):
  - Sky/Ground con rotación pitch/roll
  - Pitch ladder -90° a +90° cada 10°
  - Aircraft symbol fijo en el centro
  - Compass rotativo con yaw
  - Smooth interpolation configurable
  - Responsive via ResizeObserver
  - 60fps estables
- **Backend actualizado** para servir `frontend-vanilla/` en lugar de `frontend/build/`
  - Rutas específicas para `/css/`, `/js/`, `/logs.html`
  - Sin dependencia de build step de npm

### Eliminado
- **React UI** (deprecated): 500+ dependencias npm, 63 vulnerabilidades (15 alta, 8 crítica)
- `frontend/` (React): `node_modules/`, `package.json`, componentes JSX
- Three.js, @react-three/fiber, @react-three/drei

### Métricas de la migración
| Métrica | React (v1) | Vanilla JS (v2) |
|---------|------------|-----------------|
| Dependencias npm | 500+ | 0 |
| Vulnerabilidades | 63+ | 0 |
| Tamaño bundle | ~2MB | ~47KB |
| Tiempo de carga | ~500ms | <100ms |
| FPS horizonte | 40-50 | 60 |

---

## [1.1.0] — 2026-05-03

### Corregido
- **RSSI parsing**: Cambiado de negación de byte unsigned a `signed int8` correcto
  - Antes: `-payload[0]` → valores imposibles como -186dBm
  - Ahora: `struct.unpack('b', bytes([payload[0]]))[0]` → valores realistas -50 a -120dBm
- **CRSF Sync byte**: Corregido de `0xC8` a `0xEA` (EdgeTX Telem Mirror mode)

### Añadido
- **Link Stats completo** (10 campos): rssi1, rssi2, lq, snr, active_antenna, rf_mode, tx_power, uplink_rssi, uplink_lq, uplink_snr
- **CRSF_TYPE_CUSTOM_TELEM = 0x3A**: Captura de frames custom para análisis
- **`LinkStats` dataclass** ampliado con todos los sensores ELRS (1RSS, 2RSS, RQly, RSNR, ANT, RFMD, TPWR, TRSS, TQly, TSNR)
- Display de RF mode en pantalla (4Hz, 25Hz, 50Hz, 100Hz, 150Hz, 200Hz, 250Hz, 500Hz)

---

## [1.0.0] — 2026-05-03

### Añadido
- **`elrs_backend.py`**: Servidor FastAPI + WebSocket
  - Endpoint `/ws` para streaming en tiempo real
  - Endpoints REST: `/api/status`, `/api/history`, `/api/latest`
  - Broadcast paralelo con `asyncio.gather`
  - Reconexión automática a puerto serial
  - Multi-cliente WebSocket
- **`elrs_mobula8.py`**: Script CLI standalone para captura de telemetría
  - Parseo de frames CRSF: Link Stats (0x14), Battery (0x08), Attitude (0x1E), Flight Mode (0x21)
  - Log en JSON con timestamps UTC
  - Sistema de control de vuelo con SF switch (Manual ↔ Asistido)
  - Grabador y reproductor de maniobras
- **`session_manager.py`**: Gestión básica de sesiones JSON
- **Identificación del protocolo CRSF**:
  - Sync byte `0xEA` para EdgeTX Telem Mirror
  - 18 sensores confirmados: 1RSS, 2RSS, RQly, RSNR, ANT, RFMD, TPWR, TRSS, TQly, TSNR, RxBt, Curr, Capa, Bat%, Ptch, Roll, Yaw, FM
- **Configuración EdgeTX**: USB Serial (Debug), Channel 7 → SF switch, ARM en AUX1

---

## [0.1.0] — 2026-05-03 (Sesión inicial)

### Investigación y diagnóstico
- Identificación del protocolo CRSF sobre USB Serial
- Análisis de frames: 0x14 (Link Stats), 0x08 (Battery), 0x1E (Attitude), 0x3A (Custom)
- Confirmación de 18 sensores de telemetría disponibles
- Diagnóstico de sync byte incorrecto (0xC8 vs 0xEA)
- Captura exitosa de telemetría: `telem_20260503_113049.json`
