# Reglas de mantenimiento de documentación — Mobula8-Autopilot

Este archivo define cómo mantener `README.md`, `docs/ARCHITECTURE.md`,
`docs/ROADMAP.md` y `CHANGELOG.md`. Cualquier agente o sesión que toque el
proyecto debe seguir estas reglas.

## Regla cero: partir del repo, no de copias

Antes de tocar nada: `git status` + `git log --oneline -5` en **este**
repositorio. Nunca trabajar sobre snapshots del proyecto en otras carpetas
(descargas, backups) — la sesión del 2026-07-10 lo hizo y sus archivos
borraban la integración YOLO de v2.4.0 (ver notas de reconciliación de
v2.4.1 en `CHANGELOG.md`).

## División de responsabilidades

- **`README.md`** (raíz) — el sistema **tal como funciona hoy**, orientado a
  usarlo. Nada de futuro.
- **`docs/ARCHITECTURE.md`** — resumen arquitectónico para onboarding:
  módulos y su responsabilidad, librerías y su propósito, flujo de datos,
  decisiones de diseño. Si una sesión añade/quita una librería o módulo, o
  cambia una decisión de arquitectura, este archivo se actualiza en el
  mismo turno.
- **`docs/ROADMAP.md`** — **hacia dónde va**. Toda mejora no implementada va aquí.
- **`docs/SETUP.md`** — instalación del entorno (conda, CPU/GPU).
- **`CHANGELOG.md`** (raíz) — qué cambió y cuándo, formato Keep a Changelog.

## Estructura de carpetas (desde v2.5.0)

- `backend/` — todo el código Python. Punto de entrada:
  `python backend/elrs_backend.py`. Los módulos llegan a la raíz del repo
  con `Path(__file__).resolve().parent.parent` (para `logs/`, `models/`,
  `frontend/`); `video_config.json` vive junto al código en `backend/`.
- `frontend/` — la UI web (antes `frontend-vanilla/`).
- `docs/` — toda la documentación salvo `README.md` y `CHANGELOG.md`.
- `logs/` y `models/` — datos de runtime, fuera de git (`.gitignore`).

## Reglas fijas del README

- **Idioma**: español, consistente con el resto del proyecto.
- **No mezclar roadmap con estado actual.** Si algo no está implementado
  todavía, no va en el README; va en `ROADMAP.md`. No volver a crear una
  sección de "Mejoras Futuras" dentro del README.
- **Mantener sincronizados con el código real, en cada sesión que toque:**
  - El árbol de `## 🏗️ Arquitectura` — si se crea, mueve o borra un
    archivo, actualizar el árbol en el mismo turno, no después.
  - La tabla `## 🌐 API Endpoints` — cualquier endpoint nuevo, eliminado o
    con cambio de método/ruta debe reflejarse aquí.
  - La versión en el texto de "Salida esperada" del paso de instalación y
    cualquier referencia a versión del servidor deben coincidir con el
    valor de `version=` en el constructor de `FastAPI(...)` en
    `backend/elrs_backend.py` y con la última entrada de `CHANGELOG.md`.
  - `## 🗂️ Formato de sesiones JSON` — si `session_manager.py` cambia el
    esquema del summary o de los frames, actualizar el ejemplo JSON.
  - `## 🛠️ Troubleshooting` — cada bug recurrente que se corrija por
    segunda o tercera vez debe ganarse una entrada aquí, no solo quedar en
    el CHANGELOG. El objetivo es que Norman pueda resolverlo sin pedir
    ayuda la próxima vez que reaparezca.
  - `## 📁 Estructura de archivos` al final — debe reflejar exactamente lo
    que hay en disco.
- **Dependencias nuevas**: si una sesión agrega una dependencia Python o
  JS, añadirla a `requirements.txt` (o `requirements-yolo.txt` si es del
  pipeline de visión) y verificar que el paso de instalación del README
  sigue siendo correcto — no solo anotarla en el CHANGELOG.
- Antes de dar por cerrada una sesión de trabajo, generar el `README.md`
  **completo reescrito** (no un diff) — es la convención que Norman espera
  para todos los archivos de este proyecto.
