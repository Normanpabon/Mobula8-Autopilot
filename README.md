# Mobula8 Autopilot — alfa

Estación local para telemetría CRSF, captura y grabación de video FPV, y visión opcional con YOLO26. El panel RC existe como prototipo de banco. Su transporte PC → TX12 → receptor no está validado; **no usarlo para vuelo**. La aceptación con RadioMaster TX12, Cobra X/EasyCap y Mobula8 sigue pendiente.

## Estado de la alfa

| Área | Disponible en software | Falta validar |
|---|---|---|
| Telemetría | Puerto serial seleccionable, reconexión, contadores CRSF y sesiones JSON | Sensores reales en EdgeTX, API y navegador durante una prueba continua |
| Video | Presets analógico/digital, WebRTC y MP4 con geometría negociada | Calidad, color, latencia, desconexión USB y clips de 10 s, 60 s y 5 min con el hardware objetivo |
| Visión | Modos OFF, DETECT y SEGMENT; ROI y resultados desacoplados del stream | FPS y latencia con video real, con y sin grabación |
| RC | Deadman, propietario y época de comando, neutralización tras pérdida de mando | Ruta de entrada soportada por TX12 y canales observados en Betaflight, sin hélices |

La visión arranca en **OFF** en una instalación nueva. La selección que haga el operador se guarda localmente. `connected` en `/api/status` indica puerto abierto; `telemetry_active` exige una muestra válida reciente. Un contador de frames RC enviados solo confirma escrituras al puerto, no recepción en el dron.

## Inicio rápido

Se recomienda Python 3.11. Instalar las dependencias desde la raíz:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python backend/elrs_backend.py
```

En Windows, activar el entorno con `.venv\\Scripts\\activate`. Abrir `http://localhost:8080`. La radio se elige en **Puerto del control**; el servidor también acepta `--port` y `--baud`. Puede arrancar sin radio. Para visión, instalar además `requirements-yolo.txt`; los pesos oficiales YOLO26 se descargan mediante Ultralytics o se colocan en `models/` para uso sin conexión.

El servidor escucha en `0.0.0.0:8080` por defecto. Para limitarlo al mismo equipo, iniciar con `--host 127.0.0.1`. La guía completa de instalación y diagnóstico está en [SETUP.md](docs/SETUP.md).

## Uso

- **Video:** seleccionar capturadora y preset Digital o Analógico, iniciar el stream y luego la grabación. La UI informa resolución y FPS solicitados y negociados. Los MP4 se guardan en `logs/video/`.
- **Telemetría:** conectar el puerto de la TX12 y confirmar **Telemetría activa** junto con muestras en `/api/status`. Abrir el puerto no prueba que EdgeTX esté emitiendo sensores.
- **Visión:** abrir el panel AI, seleccionar DETECT o SEGMENT y configurar el área de inferencia. El modo SEGMENT produce cajas y máscaras con una inferencia. Los modelos locales van en `models/`.
- **Sesiones:** el servidor crea JSON en `logs/`, incluso cuando no recibe muestras, y guarda checkpoints durante la ejecución. `logs.html` permite consultarlas.
- **RC:** reservar para ensayos de banco según [RC_INJECTION.md](docs/RC_INJECTION.md) y [PLAN_ACCION.md](docs/PLAN_ACCION.md).

Las configuraciones de calibración y visión (`backend/video_config.json` y `backend/config/vision.json`) son locales y están excluidas de Git. Los pesos, grabaciones, sesiones, logs, clips de referencia y resultados de benchmark también quedan fuera del repositorio.

## Diagnóstico y pruebas de software

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
node tests/test_video_player.mjs
node tests/test_vision_roi.mjs
node tests/test_vision_panel.mjs
node tests/test_serial_controls.mjs
```

Estas pruebas usan datos sintéticos o simulados; no sustituyen la aceptación física. El log de aplicación se guarda en `logs/app/`. `--app-log-level` admite `OFF`, `ERROR`, `WARNING`, `INFO`, `DEBUG` y `TRACE`; este último registra llamadas Python y puede afectar el rendimiento. Consultar [SETUP.md](docs/SETUP.md) para las opciones de rotación.

## Documentación vigente

| Documento | Uso |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Componentes y flujo de datos |
| [SETUP.md](docs/SETUP.md) | Instalación y logging |
| [PLAN_ACCION.md](docs/PLAN_ACCION.md) | Criterios pendientes para aceptar la alfa con hardware |
| [VIDEO_PRESETS.md](docs/VIDEO_PRESETS.md) | Captura analógica y digital |
| [VISION_PIPELINE.md](docs/VISION_PIPELINE.md) | Modos YOLO26, ROI y métricas |
| [RC_INJECTION.md](docs/RC_INJECTION.md) | Alcance y limitaciones del prototipo RC |
| [ROADMAP.md](docs/ROADMAP.md) | Trabajo posterior a la alfa |
| [benchmarks/README.md](benchmarks/README.md) | Medición reproducible de visión |

`CHANGELOG.md` conserva el historial de versiones anteriores; algunas entradas describen diseños ya reemplazados por YOLO26.
