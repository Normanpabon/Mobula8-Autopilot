# Setup — Entorno de desarrollo con Conda

## Requisitos previos

- [Miniconda](https://docs.anaconda.com/miniconda/) o [Miniforge](https://github.com/conda-forge/miniforge/releases) instalado.
- Windows 10/11 o Linux. Para validar video, serial y control con el equipo
  real, seguir [`PLAN_ACCION.md`](PLAN_ACCION.md).
- Python **3.11** recomendado — versión más estable para todas las dependencias (aiortc, torch, ultralytics).

> **Nota:** El proyecto fue desarrollado con Python 3.13. Si ya tienes 3.13 y no vas a usar YOLO, puedes usarlo sin problemas. Para YOLO con GPU, quédate con 3.11.

---

## 1. Crear el entorno

```bash
conda create -n mobula8 python=3.11 -y
conda activate mobula8
```

---

## 2. Instalar dependencias core

```bash
pip install -r requirements.txt
```

Esto instala: FastAPI, uvicorn, pyserial, pydantic, numpy, opencv-python, aiortc y av.

> **Si falla `aiortc` en Windows** (error de compilación C++): instala primero las [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) y vuelve a intentarlo. Alternativa más rápida: usa la rueda pre-compilada de conda:
> ```bash
> conda install -c conda-forge aiortc -y
> pip install -r requirements.txt  # instala el resto
> ```

---

## 3. Instalar YOLO (opcional)

### CPU (cualquier máquina)
```bash
pip install -r requirements-yolo.txt
```

### GPU — CUDA 12.1
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements-yolo.txt
```

### GPU — CUDA 11.8
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
pip install -r requirements-yolo.txt
```

Verificar que CUDA es detectado:
```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## 4. Arrancar el servidor

```bash
conda activate mobula8
python backend/elrs_backend.py --port COM6 --baud 115200
```

Abre el navegador en `http://localhost:8080`.

Parámetros disponibles:

| Parámetro | Default | Descripción |
|-----------|---------|-------------|
| `--port`  | Ninguno | Puerto serial inicial opcional; también se selecciona desde la web |
| `--baud`  | 115200  | Baudrate serial |
| `--host`  | 0.0.0.0 | Bind del servidor HTTP |
| `--web-port` | 8080 | Puerto HTTP |
| `--app-log-level` | DEBUG | `OFF`, `ERROR`, `WARNING`, `INFO`, `DEBUG` o `TRACE` |
| `--app-log-dir` | `logs/app/` | Carpeta de logs del backend |
| `--app-log-max-bytes` | 10000000 | Tamaño máximo de cada archivo antes de rotar |
| `--app-log-backups` | 3 | Archivos rotados por ejecución |
| `--app-log-keep-runs` | 20 | Ejecuciones conservadas |

> **Sin radio conectada:** el servidor arranca igual y muestra el dashboard. Solo la telemetría CRSF no funcionará. El video y YOLO siguen disponibles.

### Diagnóstico de la aplicación

Por defecto se crea `logs/app/app_<fecha>_<id>_<pid>.log` a nivel `DEBUG`, con timestamps UTC e identificador de ejecución. `--app-log-level OFF` desactiva el log de eventos de la aplicación; las grabaciones MP4 y sesiones JSON siguen siendo funciones independientes. Los mismos parámetros se pueden fijar con `MOBULA_LOG_LEVEL`, `MOBULA_LOG_DIR`, `MOBULA_LOG_MAX_BYTES`, `MOBULA_LOG_BACKUPS` y `MOBULA_LOG_KEEP_RUNS`.

```bash
# Prueba con diagnóstico normal
python backend/elrs_backend.py --app-log-level DEBUG

# Diagnóstico exhaustivo: registra cada llamada a funciones Python de backend/
python backend/elrs_backend.py --app-log-level TRACE

# Prueba de rendimiento sin logging de aplicación
python backend/elrs_backend.py --app-log-level OFF
```

`TRACE` registra las llamadas a funciones Python de `backend/` (excepto el propio módulo de logging), con nombre, archivo y línea, sin argumentos. Genera muchos eventos y puede aumentar la latencia; úsalo solo para reproducir un defecto. En el navegador se registran eventos y errores relevantes; el navegador no ofrece un hook general para cada llamada a función JavaScript. `DEBUG` conserva eventos HTTP, transiciones seriales, contadores periódicos, muestras hexadecimales acotadas de tramas descartadas, valores de telemetría aceptados, comandos RC, video, visión y errores del navegador. `GET /api/status` muestra bytes recibidos, CRC fallidos, tramas válidas, muestras aceptadas por tipo y la edad de la última telemetría. `connected` significa puerto abierto; `telemetry_active` significa una muestra válida en los últimos cinco segundos.

Cada sesión tiene un JSON en `logs/`, incluso si recibió cero frames. Mientras está activa se guarda un checkpoint atómico aproximadamente cada diez segundos; al desconectar o cerrar el servidor se marca finalizada. Los logs de aplicación rotan a 10 MB y conservan tres copias por ejecución y las veinte ejecuciones más recientes, salvo que se configuren otros límites.

---

## 5. Calibrar video (opcional)

```bash
python backend/video_calibrate.py --device 0
```

Controles: `B/C/S/G` ajustan brillo/contraste/saturación/gamma. `W` guarda en `video_config.json`.

---

## 6. Comandos útiles de conda

```bash
# Ver entornos disponibles
conda env list

# Desactivar entorno actual
conda deactivate

# Eliminar entorno
conda env remove -n mobula8

# Exportar entorno reproducible
conda env export > environment.yml

# Recrear desde el export
conda env create -f environment.yml
```

---

## Estructura de carpetas relevante

```
Mobula8-Autopilot/
├── backend/
│   ├── elrs_backend.py    # Servidor principal — punto de entrada
│   ├── video_streamer.py  # Captura USB + WebRTC
│   ├── vision_model.py    # Modelo YOLO26 (requiere ultralytics)
│   ├── vision_pipeline.py # Inferencia, ROI y overlay
│   ├── session_manager.py # Persistencia de sesiones de vuelo
│   ├── video_calibrate.py # Herramienta de calibración de color
│   └── video_config.json  # Configuración local de video, ignorada por Git
├── frontend/              # UI web (sin npm, vanilla JS)
│   ├── index.html         # Dashboard principal
│   └── logs.html          # Explorador de sesiones
├── docs/                  # Instalación, arquitectura y aceptación alfa
├── models/                # Coloca aquí modelos .pt personalizados
└── logs/                  # Sesiones JSON, eventos y videos grabados
    ├── app/
    └── video/
```

Ver `docs/ARCHITECTURE.md` para el detalle de módulos, librerías y flujo de datos.
