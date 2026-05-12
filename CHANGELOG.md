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
