# Setup — Entorno de desarrollo con Conda

## Requisitos previos

- [Miniconda](https://docs.anaconda.com/miniconda/) o [Miniforge](https://github.com/conda-forge/miniforge/releases) instalado.
- Windows 10/11 (el proyecto usa DirectShow para captura de video).
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
| `--port`  | COM6    | Puerto serial del EdgeTX |
| `--baud`  | 115200  | Baudrate serial |
| `--host`  | 0.0.0.0 | Bind del servidor HTTP |
| `--web-port` | 8080 | Puerto HTTP |

> **Sin radio conectada:** el servidor arranca igual y muestra el dashboard. Solo la telemetría CRSF no funcionará. El video y YOLO siguen disponibles.

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
│   ├── yolo_processor.py  # Pipeline YOLO (requiere ultralytics)
│   ├── session_manager.py # Persistencia de sesiones de vuelo
│   ├── video_calibrate.py # Herramienta de calibración de color
│   └── video_config.json  # Configuración de video guardada
├── frontend/              # UI web (sin npm, vanilla JS)
│   ├── index.html         # Dashboard principal
│   └── logs.html          # Explorador de sesiones
├── docs/                  # SETUP, ARCHITECTURE, ROADMAP, AGENT_HANDOFF
├── models/                # Coloca aquí modelos .pt personalizados
└── logs/                  # Sesiones JSON y videos grabados
    └── video/
```

Ver `docs/ARCHITECTURE.md` para el detalle de módulos, librerías y flujo de datos.
