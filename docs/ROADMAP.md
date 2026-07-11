# Roadmap — Mobula8-Autopilot

Este archivo reemplaza la sección "🔮 Mejoras Futuras" que antes vivía dentro
de `README.md`. El README describe el sistema **tal como funciona hoy**; este
archivo describe **hacia dónde va**. Ver `AGENT_HANDOFF.md` para las reglas
de cómo mantener ambos documentos.

Última actualización: 2026-07-11 (tras v2.6.0 — pipeline de visión en
cascada segmentación + YOLO desacoplado del stream, LatencyGovernor y guía
de fine-tuning; ver `VISION_PIPELINE.md` y `YOLO_FINETUNING.md`).

---

## 🔴 Bloqueante — antes de cualquier otra cosa

- [ ] **Validar en runtime** las correcciones de v2.4.1/v2.5.0 con hardware real
      (TX12 + Mobula8 + EasyCap conectados). Todo se verificó por importación
      del backend, `py_compile` y `node --check`, no por ejecución del stream
      WebRTC real.
- [x] ~~Mover `VideoPlayer.js` a `frontend-vanilla/js/modules/`~~ — resuelto
      en v2.4.1 (2026-07-10). El archivo de la raíz (que además traía el fix
      de reconexión) se absorbió en `frontend-vanilla/js/modules/VideoPlayer.js`.

## 🟡 Corto plazo

- [ ] Confirmar que el balance de blancos por canal (`wb_r/wb_g/wb_b`) corrige
      el tinte magenta de la EasyCap en la práctica; ajustar el preset
      `anti_magenta` (`wb_r: 0.75, wb_g: 1.10, wb_b: 0.75`) si el valor real
      difiere. Usar `python backend/video_calibrate.py` (tecla `I` aplica el
      preset, `R/E/U` ajustan por canal, `W` guarda).
- [ ] Validar el pipeline de visión (v2.6.0) sobre el stream real de la
      EasyCap: FPS de visión alcanzables en el laptop, si el modo `mask` de
      la segmentación reduce falsos positivos en video analógico con ruido,
      y confirmar que el stream mantiene sus FPS con la inferencia
      desacoplada (las cifras actuales vienen de frames sintéticos; ver
      `VISION_PIPELINE.md` §6).
- [ ] Primer fine-tuning con dataset propio siguiendo `YOLO_FINETUNING.md`:
      grabar sesiones variadas, etiquetar, entrenar yolov8n@416 y comparar
      latencia/precisión contra el COCO genérico. Evaluar entonces si la
      etapa de segmentación sigue aportando o se retira.
- [ ] Export ONNX / OpenVINO INT8 del modelo fine-tuneado y medición del
      speedup real en este laptop (tabla de expectativas en
      `YOLO_FINETUNING.md` §6).
- [ ] Exportación CSV de sesiones (para análisis en Excel/Python) —
      mencionado como pendiente desde v1.0.0, nunca implementado.
- [ ] Comparación de sesiones: superponer métricas de dos o más vuelos en
      `logs.html`.
- [ ] Alertas configurables por umbral (voltaje mínimo, RSSI, pérdida de LQ).
- [x] ~~Añadir `.gitignore` para `__pycache__/`~~ — resuelto en v2.5.0
      (`.gitignore` creado; `__pycache__/` fuera del tracking).

## 🟢 Medio plazo — Fase 3: Inyección de comandos EdgeTX

- [ ] `command_injector.py`: escritura de frames CRSF RC Channels (0x16)
      hacia la TX12 por USB
- [ ] Deadman switch: canales vuelven a posición neutral si se pierde
      conexión >500 ms
- [ ] Endpoints `POST /api/rc/channels` y `WS /ws/rc`
- [ ] Panel de control manual en la UI (sliders throttle/pitch/roll/yaw +
      Web Gamepad API)
- [ ] **Pendiente de validación de protocolo**: confirmar si la TX12 acepta
      CRSF de entrada desde la PC en modo serial, o si se requiere el modo
      Joystick USB HID de EdgeTX
- [ ] GPS y visualización de trayectoria en mapa (requiere módulo GPS,
      el Mobula8 no trae uno de fábrica)
- [ ] Compresión de logs JSON (gzip) — los archivos de sesión crecen sin
      límite con vuelos largos

## 🔵 Largo plazo — Fase 4: Vuelo autónomo

- [ ] `autopilot.py`: motor de control autónomo con máquina de estados
      (IDLE → ARM → TAKEOFF → MISSION → LAND → DISARM)
- [ ] Loop visión → decisión → comando usando telemetría + detecciones YOLO,
      integrando el `LatencyGovernor` de v2.6.0: saturar la velocidad
      comandada con `governor.max_speed_ms`, hover en modo `stale`, y
      degradar visión (bajar `imgsz` / apagar segmentación) antes que
      perder frescura — reglas completas en `VISION_PIPELINE.md` §4.
- [ ] Medir `reaction_time_ms` real (decisión + inyección CRSF + uplink +
      respuesta del drone) cuando exista la Fase 3, y recalibrar el governor
      (hoy usa 250 ms estimados).
- [ ] Evaluar compensación predictiva de latencia (Kalman con actitud CRSF
      para extrapolar detecciones) como alternativa a limitar velocidad
      (`VISION_PIPELINE.md` §4, alternativas consideradas).
- [ ] Controlador PID sobre pitch/roll para hover estabilizado
- [ ] Modo Follow target: centra el objeto detectado ajustando yaw/pitch
- [ ] Modo Return to safe: aterrizaje automático por batería baja o pérdida
      de RSSI
- [ ] Safety: límites de canal configurables, watchdog de telemetría,
      logging de decisiones
- [ ] Deploy permanente en Jetson Nano u otro sistema embebido (sacar el
      sistema del laptop de desarrollo)
- [ ] Autenticación básica para exponer el servidor en redes no confiables
      (hoy `--host 0.0.0.0` expone todo sin login)
- [ ] Evaluar si el techo de alcance real (~1.5–2 km, limitado por los
      ~10 mW de downlink del receptor ELRS del Mobula8) es aceptable para
      el caso de uso de monitoreo autónomo, o si requiere cambiar de
      receptor/drone

---

## Fuera de alcance (decisiones ya tomadas, no reabrir sin justificación)

- **React en el frontend**: migrado a Vanilla JS en v2.0.0 por reducción de
  dependencias (500+ → 0) y vulnerabilidades (63+ → 0). No revertir.
- **STUN/TURN externos para WebRTC**: el uso previsto es LAN local; no
  añadir infraestructura de NAT traversal salvo que cambie el caso de uso.
- **Trabajar sobre snapshots del proyecto fuera del repo**: la sesión del
  2026-07-10 partió de una copia vieja (~v2.3.0) y sus archivos borraban la
  integración YOLO de v2.4.0. Cualquier sesión debe partir de `git status` +
  `git log` de **este** repositorio, nunca de copias en carpetas de descargas.
