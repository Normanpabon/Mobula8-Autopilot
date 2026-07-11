# Arquitectura — Mobula8-Autopilot

Resumen arquitectónico del sistema para que un desarrollador nuevo pueda
incorporarse al proyecto sin más contexto que este documento, `SETUP.md`
(instalación) y el `README.md` (uso). Última actualización: v2.7.0.

---

## 1. Qué es el sistema

Una estación de tierra para el drone **Mobula8** (whoop de 65 mm con
receptor ELRS) controlado por un **RadioMaster TX12** (EdgeTX). Corre en un
laptop Windows y hace cuatro cosas:

1. **Telemetría**: lee los frames CRSF que la TX12 refleja por USB serial
   (modo Telem Mirror), los parsea y los transmite en vivo al navegador.
2. **Video FPV**: captura el video analógico del drone via una capturadora
   USB (EasyCap) y lo sirve al navegador por WebRTC, con grabación MP4
   opcional sincronizada con la sesión de telemetría.
3. **Visión (segmentación + YOLO)**: pipeline opcional de dos etapas
   conmutables — segmentación de regiones y detección de objetos — que corre
   desacoplado del stream y dibuja sus resultados (y la latencia medida)
   sobre el video. Un `LatencyGovernor` traduce esa latencia en una
   velocidad máxima recomendada para el futuro autopilot
   (ver `docs/VISION_PIPELINE.md`).
4. **Inyección RC (Fase 3)**: envía frames CRSF RC Channels (0x16) de
   vuelta a la TX12 por el mismo USB serial, con deadman switch y panel de
   control manual (sliders/gamepad). ⚠ Pendiente de validar que EdgeTX
   acepte CRSF entrante en modo Telem Mirror (ver `docs/RC_INJECTION.md`).

El objetivo de largo plazo (ver `ROADMAP.md`) es cerrar el lazo:
telemetría + visión → decisión → inyección de comandos RC de vuelta a la
TX12 (vuelo asistido/autónomo). Con v2.7.0 las piezas 1–4 existen; falta el
motor de decisión (`autopilot.py`, Fase 4) y la validación con hardware.

## 2. Diagrama de flujo de datos

```
                 USB serial (CRSF @ 115200)            USB (video analógico digitalizado)
  TX12 (EdgeTX) ────────────────────────────┐    ┌──────────────────────── EasyCap ── cámara FPV
                                            ▼    ▼
                                   ┌─────────────────────┐
                                   │  backend/ (Python)  │
                                   │                     │
   serial_reader_task ──► parse_crsf_frame ──► broadcast │
        │        ▲                               │ WS    │
        │   CommandInjector ◄── /api/rc, /ws/rc  │       │
        │   (frames RC 0x16 + deadman)           │       │
        └──► SessionManager ──► logs/*.json      │       │
                                                 │       │
   VideoCapture ─► correcciones ─► overlay ─► FPVVideoTrack ─► WebRTC (aiortc)
        │            (WB/gamma)       ▲                            │
        │      VisionPipeline (loop propio, 1 worker):             │
        ├────► [segmentación] ─► [YOLO] ─► LatencyGovernor         │
        │                                                          │
        └────────► VideoRecorder ─► logs/video/*.mp4               │
                                   └─────────────────────┘        │
                                            ▲                     ▼
                                   ┌─────────────────────────────────────┐
                                   │  frontend/ (Vanilla JS, sin build)  │
                                   │  WebSocket /ws  ←─ telemetría       │
                                   │  RTCPeerConnection ←─ video         │
                                   │  fetch /api/* ←─ control            │
                                   └─────────────────────────────────────┘
```

Todo corre en un solo proceso (`python backend/elrs_backend.py`): FastAPI
sirve API + frontend estático, el lector serial es una task asyncio, y la
captura de video corre en el mismo event loop. La inferencia de visión corre
en un loop asyncio propio que delega a un thread (1 worker) y **no bloquea
el stream**: el track WebRTC solo dibuja el último resultado publicado.

## 3. Módulos del backend (`backend/`)

| Módulo | Responsabilidad | Piezas clave |
|--------|-----------------|--------------|
| `elrs_backend.py` | **Punto de entrada.** Servidor FastAPI: parseo CRSF, WebSocket de telemetría, ~25 endpoints REST, servido del frontend. Carga el módulo de video de forma opcional (si falla, solo se desactiva el video). | `parse_crsf_frame()`, `crc8_dvb_s2()` (tabla precomputada), `ConnectionManager` (broadcast WS), `serial_reader_task()`, patrón `lifespan` |
| `session_manager.py` | Persistencia de sesiones de vuelo. Acumula frames en memoria y al cerrar calcula el resumen (voltajes, RSSI, LQ, actitud) y guarda JSON en `logs/`. | `SessionManager`, `save()`, `_compute_summary()` |
| `video_streamer.py` | Pipeline completo de video: enumeración de capturadoras, captura OpenCV, correcciones de imagen, track WebRTC y grabación MP4. Conecta el `VisionPipeline` al ciclo de vida de la captura. | `DeviceManager` (enumeración paralela MSMF→DSHOW, nombres via `Win32_PnPEntity`), `VideoCapture`, `apply_white_balance()`, `FPVVideoTrack` (recibe un `frame_getter` async — desacoplado de la fuente), `WebRTCManager` (un `RTCPeerConnection` por cliente), `VideoRecorder`, `VideoStreamer` (fachada; `.yolo` es alias del detector para compatibilidad) |
| `vision_pipeline.py` | Orquestador de la cascada de visión: loop de inferencia desacoplado del stream (ThreadPoolExecutor de 1 worker), overlay barato (`annotate()`, solo cv2), y política de latencia para el futuro autopilot. Ver `docs/VISION_PIPELINE.md`. | `VisionPipeline`, `VisionResult`, `LatencyGovernor` (v_max = distancia de seguridad / latencia total; modos off/warming_up/active/stale) |
| `yolo_processor.py` | Etapa de detección: wrapper síncrono del modelo YOLO (`.pt`/`.onnx`/`.engine`), `imgsz` configurable. Falla silenciosamente si `ultralytics` no está instalado. | `YOLOProcessor`, `infer()` (devuelve detecciones con bbox en píxeles), `list_local_models()` (excluye `-seg`) |
| `segmentation_processor.py` | Etapa opcional de segmentación previa a la detección: máscara binaria de regiones con objetos, dilatada con margen. `focus_mode="mask"` suprime el fondo antes del detector; `"overlay"` solo dibuja. | `SegmentationProcessor`, `segment()`, `apply_focus()`, `list_local_models()` (solo `-seg`) |
| `command_injector.py` | Inyección RC (Fase 3): frames CRSF RC Channels Packed (0x16, 16×11 bits) hacia la TX12 por el serial compartido, loop de envío a 50 Hz y deadman switch (>500 ms sin comandos → throttle mínimo, ejes centrados). Pendiente validación de protocolo con hardware. Ver `docs/RC_INJECTION.md`. | `CommandInjector`, `build_rc_frame()`, `set_channels()` (alias AETR o índice 1–16, µs), propiedad `failsafe_active` |
| `video_calibrate.py` | Herramienta standalone (ventana OpenCV) para calibrar brillo/contraste/gamma/balance de blancos. Guarda en `video_config.json`, que el streamer lee. | Presets WB (`anti_magenta` para el tinte de la EasyCap), ajuste por canal con teclas |

Convención de rutas: los módulos usan `Path(__file__).resolve().parent.parent`
para llegar a la raíz del repo (`logs/`, `models/`, `frontend/`);
`video_config.json` vive junto al código en `backend/`.

## 4. Módulos del frontend (`frontend/`)

Sin npm, sin build step, sin dependencias: HTML + ES modules servidos
directamente por FastAPI. Decisión tomada en v2.0.0 al eliminar React
(500+ deps, 63 vulnerabilidades → 0).

| Archivo | Responsabilidad |
|---------|-----------------|
| `index.html` | Dashboard principal: player WebRTC, panel de ajustes de video, panel AI (YOLO), telemetría en vivo. Contiene su propio JS de página. |
| `logs.html` | Explorador de sesiones: gráficas Canvas 2D, playback del horizonte con scrubber. |
| `js/app.js` | Bootstrap: WebSocket manager con auto-reconnect. |
| `js/config.js` | Configuración centralizada (smoothing, umbrales). |
| `js/modules/TelemetryManager.js` | Estado reactivo por eventos. |
| `js/modules/HorizonCanvas.js` | Horizonte artificial Canvas 2D a 60 fps (pitch ladder, compass). |
| `js/modules/VideoPlayer.js` | Cliente WebRTC: señalización SDP via `POST /offer`, reconexión con backoff exponencial, control de grabación. |
| `js/modules/PerformanceMonitor.js` | Overlay de FPS/latencia (tecla F2). |
| `js/modules/Utils.js` | Helpers de formateo y Canvas. |

## 5. Librerías y su propósito

### Python (`requirements.txt` — core)

| Librería | Para qué se usa aquí |
|----------|----------------------|
| **fastapi** | Framework del servidor: rutas REST, WebSocket `/ws`, validación con Pydantic, `lifespan` para startup/shutdown. |
| **uvicorn[standard]** | Servidor ASGI que ejecuta la app. `[standard]` trae websockets y httptools. |
| **pydantic** | Modelos de request (`VideoStartRequest`, `YOLOConfigRequest`) — el body parsing de FastAPI depende de esto. |
| **pyserial** | Lectura del puerto COM donde la TX12 refleja la telemetría CRSF. |
| **numpy** | Manipulación de frames como arrays (balance de blancos por canal, clipping). |
| **opencv-python** | Captura de video USB (backends MSMF/DSHOW), correcciones de imagen, escritura MP4, ventana de calibración. |
| **aiortc** | WebRTC en Python: `RTCPeerConnection`, negociación SDP, codificación del stream hacia el navegador. |
| **av** (PyAV) | `VideoFrame`: puente entre los arrays numpy de OpenCV y los frames que aiortc transmite. |

### Python (`requirements-yolo.txt` — opcional)

| Librería | Para qué se usa aquí |
|----------|----------------------|
| **ultralytics** | Carga e inferencia de modelos YOLOv8/v11 de detección y segmentación (`.pt`, y `.onnx`/`.engine`/OpenVINO exportados — ver `docs/YOLO_FINETUNING.md`). Arrastra PyTorch; para GPU instalar torch con CUDA antes (ver `SETUP.md`). |

El servidor arranca sin este grupo: los procesadores de visión se importan
de forma opcional y los endpoints `/api/vision/*`, `/api/yolo/*` y
`/api/segmentation/*` responden "no disponible". Los extras de optimización
(`onnxruntime`, `openvino`) solo hacen falta para los formatos exportados.

### Frontend

Cero dependencias externas. APIs nativas del navegador: **WebSocket**
(telemetría), **RTCPeerConnection** (video), **Canvas 2D** (horizonte y
gráficas), **ES modules** (organización del código).

## 6. Protocolos e interfaces

- **CRSF sobre USB serial** — sync byte `0xEA` (modo Telem Mirror de
  EdgeTX, no el `0xC8` estándar), CRC8 DVB-S2. Frames parseados: Link
  Stats (`0x14`), Battery (`0x08`), Attitude (`0x1E`), Flight Mode (`0x21`).
  En sentido contrario (v2.7.0), frames RC Channels Packed (`0x16`)
  inyectados por el mismo puerto — dirección configurable (`0xEE`/`0xEA`/
  `0xC8`) porque la aceptación por EdgeTX está pendiente de validación.
- **WebSocket `/ws`** — JSON por frame de telemetría hacia todos los
  clientes conectados (broadcast con `asyncio.gather`).
- **WebSocket `/ws/rc`** — canal de baja latencia del panel de control
  manual/gamepad hacia el `CommandInjector` (10 Hz desde la UI; el deadman
  cubre la desconexión).
- **WebRTC** — señalización HTTP simple: el browser hace `POST /offer` con
  su SDP, el backend responde con el answer. Sin STUN/TURN: uso LAN local
  (decisión registrada en `ROADMAP.md`).
- **REST `/api/*`** — control y consulta; tabla completa en el README.
  Orden de registro crítico: el catch-all `GET /{full_path:path}` que sirve
  el frontend **debe ser la última ruta registrada** o intercepta la API
  (bug histórico, corregido en v2.3.1).

## 7. Presupuesto de latencia (medido/estimado)

| Tramo | Latencia |
|-------|----------|
| EasyCap (digitalización NTSC) | ~50–100 ms |
| Pipeline aiortc (encode + red local) | ~150–250 ms |
| Telemetría CRSF (ratio 1:8 + refresh Fast) | ~30–60 ms |
| Detección YOLOv8n (CPU laptop, imgsz 640/416) | ~120–150 / ~50–80 ms/frame |
| Segmentación yolov8n-seg (CPU, imgsz 416) | ~55–90 ms/frame |
| Cascada seg + det | ~135–175 ms/frame |

Desde v2.6.0 la inferencia **no** suma latencia al stream (corre
desacoplada); lo que introduce es *edad* en los resultados de visión. El
`LatencyGovernor` convierte la latencia total cámara→decisión→drone en una
velocidad máxima recomendada, y encender más etapas la reduce — desglose
completo y política del autopilot en `docs/VISION_PIPELINE.md`.

Implicación: la telemetría llega antes que el video. Cualquier lógica de
control futura (Fase 3/4) debe decidir sobre telemetría y usar la visión
como señal lenta, o mover la inferencia a GPU/edge.

## 8. Decisiones de arquitectura (no reabrir sin justificación)

1. **Vanilla JS, sin build** — menos superficie de ataque y cero mantenimiento
   de dependencias (v2.0.0).
2. **Sin STUN/TURN** — solo LAN local.
3. **JSON plano en `logs/`** — sin base de datos; el volumen de datos no lo
   justifica todavía (gzip pendiente en roadmap).
4. **Balance de blancos por software** — el driver de la EasyCap ignora
   `CAP_PROP_WB_*`; se corrige por canal en numpy.
5. **Carga opcional de video y YOLO** — el servidor de telemetría nunca debe
   caer por un problema de video (`except Exception` en la carga, v2.4.1).
6. **Un solo proceso** — sencillez de operación en campo; si el YOLO en CPU
   se queda corto, la salida prevista es GPU o Jetson, no microservicios.

## 9. Onboarding — por dónde empezar

1. Instala el entorno con `docs/SETUP.md` y arranca:
   `python backend/elrs_backend.py` (funciona sin radio ni cámara: verás el
   dashboard con el video desactivado).
2. Lee `backend/elrs_backend.py` de arriba a abajo (~450 líneas): define
   casi todo el contrato del sistema.
3. Swagger en `http://localhost:8080/docs` para jugar con la API.
4. Antes de tocar código: reglas de documentación en `AGENT_HANDOFF.md`
   (incluida la regla cero: partir siempre de este repo, nunca de copias).
5. El trabajo pendiente priorizado está en `ROADMAP.md`; el historial de
   decisiones, en `CHANGELOG.md`.
