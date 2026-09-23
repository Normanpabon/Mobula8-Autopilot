# Arquitectura de la alfa

El punto de entrada es `python backend/elrs_backend.py`. FastAPI sirve la API, WebSockets y el frontend estático. `SerialManager` es el único propietario del puerto serial. `VideoStreamer` administra captura, WebRTC y MP4. La visión usa un worker de inferencia de un solo hilo; WebRTC consume el último resultado disponible sin esperar una inferencia nueva.

```text
TX12 / serial → SerialManager → parser CRSF → API / WebSocket → navegador
                                       └→ SessionManager → logs/session_*.json
capturadora USB → VideoCapture ┬→ VideoRecorder → logs/video/*.mp4
                               ├→ VisionPipeline → último resultado / overlay
                               └→ FPVVideoTrack → WebRTC → navegador
panel RC → CommandInjector → SerialManager → TX12 (transporte físico pendiente)
```

## Módulos

| Ruta | Responsabilidad |
|---|---|
| `backend/elrs_backend.py` | Ciclo de vida, parser CRSF, estado y rutas API |
| `backend/serial_manager.py` | Apertura, lectura, escritura y reintentos seriales |
| `backend/session_manager.py` | Sesiones JSON y checkpoints atómicos |
| `backend/video_streamer.py` | Captura, calibración, WebRTC y grabación |
| `backend/vision_config.py` | Esquema y persistencia de configuración de visión |
| `backend/vision_model.py` | Carga y normalización de resultados YOLO26 |
| `backend/vision_pipeline.py` | ROI, worker, overlay y métricas de latencia |
| `backend/command_injector.py` | Frames RC, deadman y propiedad del canal de mando |
| `backend/app_logging.py` | Log por ejecución, rotación y niveles configurables |
| `frontend/` | Dashboard, reproductor, controles y explorador de sesiones |

## Datos locales

`logs/` contiene eventos, sesiones y MP4. `models/` contiene pesos descargados o propios. La calibración de video (`backend/video_config.json`), la configuración de visión (`backend/config/vision.json`) y el ROI son elecciones del operador. Estos datos están excluidos de Git; un clon nuevo usa los valores predeterminados del código, con visión en OFF.

Los presets de captura solicitan un formato, pero el driver puede negociar otro. El frame real alimenta grabación, visión y WebRTC. El track de video no espera la inferencia; la edad del resultado se expone en el estado de visión. Esto evita una dependencia directa entre cada frame transmitido y cada inferencia, aunque la contención de CPU/GPU puede afectar la latencia total. Las métricas sintéticas no son una medida de latencia de pilotaje.

## Límites de la alfa

- El stream de video y la grabación comparten el proceso. Una lectura bloqueada dentro del driver USB aún puede impedir un cierre acotado.
- El parser CRSF acepta un conjunto limitado de tipos de telemetría y la cabecera configurada en el código. El estado distingue puerto abierto, frames válidos y telemetría reciente.
- El deadman RC funciona mientras el proceso y el event loop sigan ejecutándose. Falta confirmar que la TX12 acepte comandos por la ruta física propuesta y que el receptor los reciba.
- No hay autenticación para acceso desde redes no confiables. Limitar `--host` a `127.0.0.1` cuando no se necesite acceso remoto.

Los criterios de aceptación física están en [PLAN_ACCION.md](PLAN_ACCION.md); la configuración de visión está en [VISION_PIPELINE.md](VISION_PIPELINE.md).
