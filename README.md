# ELRS Telemetry System — Mobula8

Sistema completo de telemetría en tiempo real y registro de vuelos para Mobula8 con RadioMaster TX12 y protocolo ELRS.

---

## 🎯 Descripción del Proyecto

Este sistema captura, visualiza y almacena la telemetría del drone Mobula8 en tiempo real a través de conexión USB serial desde el RadioMaster TX12 (EdgeTX). Proporciona una interfaz web completa accesible desde cualquier dispositivo en la red local.

### Qué hace
- **Captura telemetría CRSF** directamente desde el control remoto via USB
- **Visualiza en tiempo real**: horizonte artificial, batería, señal RF, modos de vuelo
- **Registra automáticamente** cada sesión de vuelo en formato JSON
- **Explorador de vuelos**: revive cualquier vuelo con gráficas y playback del horizonte

### Stack técnico
- **Backend**: Python 3.8+ / FastAPI / WebSocket / pySerial
- **Frontend**: Vanilla JavaScript (sin dependencias npm)
- **Protocolo**: CRSF sobre USB Serial (EdgeTX Telem Mirror)
- **Almacenamiento**: JSON plano en disco (`logs/`)

---

## 🏗️ Arquitectura

```
elrs_backend.py          ← Servidor principal (FastAPI)
session_manager.py       ← Gestión de sesiones de vuelo
frontend-vanilla/
├── index.html           ← UI en tiempo real
├── logs.html            ← Explorador de sesiones
├── css/main.css
└── js/
    ├── app.js
    ├── config.js
    └── modules/
        ├── HorizonCanvas.js      ← Horizonte artificial (Canvas 2D)
        ├── TelemetryManager.js   ← Estado reactivo
        ├── PerformanceMonitor.js ← Monitor de latencia (F2)
        └── Utils.js
logs/
└── session_YYYYMMDD_HHMMSS.json ← Sesiones guardadas
```

---

## 🚀 Instalación y Ejecución

### Requisitos

- Python 3.8 o superior
- RadioMaster TX12 con EdgeTX
- Mobula8 con ELRS receptor
- Cable USB (datos, no solo carga)
- Navegador moderno (Chrome 90+, Firefox 88+)

### 1. Instalar dependencias Python

```bash
pip install fastapi uvicorn websockets pyserial
```

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
ELRS Telemetry Server v2.0 | COM6@115200 | http://localhost:8080
[SESSION] Nueva sesión: 20260503_180000
[SESSION] Logs en: A:\...\logs
[SERIAL] Conectado a COM6 @ 115200 baud
[SERVER] ELRS Telemetry Server v2.0 listo
```

### 5. Abrir la interfaz web

| URL | Descripción |
|-----|-------------|
| `http://localhost:8080` | Vista en tiempo real |
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

---

## 🔮 Mejoras Futuras

- **Video FPV**: Streaming WebRTC/HLS desde cámara del drone
- **GPS y mapa**: Visualización de trayectorias en mapa (con módulo GPS)
- **Alertas configurables**: Alarmas por voltaje, RSSI, modo de vuelo
- **Comparación de sesiones**: Superponer métricas de diferentes vuelos
- **Control asistido**: Modo de vuelo autónomo via MSP desde la UI
- **Exportación CSV**: Para análisis en Excel o Python
- **Compresión de logs**: Reducir tamaño de archivos JSON con gzip
- **Autenticación**: Login para acceso seguro en redes no confiables
- **Deploy en Jetson Nano**: Guía completa de sistema embebido permanente

---

## 📁 Estructura de archivos

```
.
├── elrs_backend.py          ← Servidor principal (EJECUTAR ESTE)
├── session_manager.py       ← Módulo de sesiones (no ejecutar solo)
├── elrs_mobula8.py          ← CLI standalone (opcional, para debug)
├── diagnostic_serial.py     ← Diagnóstico de puerto serial
├── frontend-vanilla/        ← Interfaz web (copiar junto al backend)
│   ├── index.html
│   ├── logs.html
│   ├── css/
│   └── js/
├── logs/                    ← Sesiones guardadas (se crea automático)
│   └── session_*.json
└── README.md
```
