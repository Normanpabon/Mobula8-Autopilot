# Validación con Hardware Real — v2.5.0

Checklist de pruebas manuales para cerrar el ítem bloqueante del
`ROADMAP.md`: *"Validar en runtime las correcciones de v2.4.1/v2.5.0 con
hardware real"*. Hasta ahora todo se verificó solo por `py_compile`,
import del backend y `node --check` — ningún test aquí requiere escribir
código nuevo, son pasos de ejecución real con el hardware conectado.

**Hardware necesario:** RadioMaster TX12 (EdgeTX, modo Telem Mirror) por
USB, cámara EasyCap (capturadora analógica), drone Mobula8 (solo para las
pruebas de RF/VTX, no hace falta que vuele).

Marca cada casilla al validar. Si algo falla, anota el síntoma exacto
(log, screenshot, código de error) antes de pasar al siguiente bloque —
son prerequisito unos de otros en el orden dado.

---

## 0. Arranque del servidor

- [ ] `python backend/elrs_backend.py --port COM6 --baud 115200` arranca sin
      excepciones con la TX12 **conectada** por USB.
- [ ] Repetir con la TX12 **desconectada**: el servidor debe arrancar igual
      (dashboard visible, telemetría simplemente no llega) — confirma el
      comportamiento documentado en `SETUP.md`.
- [ ] `http://localhost:8080` carga el dashboard (`index.html`) sin errores
      404 de CSS/JS en la consola del navegador (rutas `/css/*` y `/js/*`
      movidas a `frontend/` en v2.5.0 — punto más probable de romperse tras
      la reestructuración).
- [ ] `http://localhost:8080/logs.html` carga el explorador de sesiones.
- [ ] Confirmar en consola del proceso que las rutas resueltas por
      `Path(__file__).resolve().parent.parent` apuntan a las carpetas reales
      (`logs/`, `models/`, `frontend/`) y no a rutas rotas por el move a
      `backend/`.

## 1. Telemetría CRSF (TX12 → PC)

- [ ] `GET /api/status` devuelve `connected: true` y campos no nulos
      (voltaje, RSSI, LQ) con la TX12 encendida y en modo Telem Mirror.
- [ ] El WebSocket `/ws` empuja actualizaciones en vivo — confirmar en el
      dashboard que los valores se refrescan sin recargar la página.
- [ ] `GET /api/latest` y `GET /api/history` devuelven datos consistentes
      con lo mostrado en pantalla.
- [ ] Apagar la TX12 en pleno vuelo/prueba: el backend no debe crashear;
      `connected` debe pasar a `false` y el dashboard reflejar la
      desconexión (deadman/timeout de telemetría).
- [ ] Reconectar la TX12 sin reiniciar el servidor: la telemetría debe
      retomar sola (probar el sync byte `0xEA` en reconexión, no solo en
      arranque en frío).

## 2. Sesiones de vuelo

- [ ] `POST /api/sessions/save` persiste una sesión con datos reales de la
      TX12 (no placeholders).
- [ ] `GET /api/sessions` lista la sesión recién guardada;
      `GET /api/sessions/{id}` y `.../summary` devuelven el detalle
      correcto.
- [ ] Verificar el JSON en `logs/` a nivel de archivo: campos completos,
      sin truncar, timestamps coherentes con la duración real de la prueba.

## 3. Video — EasyCap + WebRTC (Fase 1, foco principal del bloqueo)

- [ ] `GET /api/video/devices` lista la EasyCap entre los dispositivos
      disponibles (índice DirectShow correcto).
- [ ] `POST /api/video/start` con el índice de la EasyCap arranca la
      captura sin excepción MSMF/DSHOW.
- [ ] El stream WebRTC llega al navegador y se ve en el dashboard — este es
      el punto que *nunca* se probó en runtime real, es la prueba más
      importante de todo este documento.
- [ ] Medir la latencia percibida extremo a extremo (EasyCap → WebRTC →
      navegador). Roadmap estima ~150–250 ms (aiortc) + ~50–100 ms
      (EasyCap); confirmar que el total percibido es utilizable para
      pilotaje FPV o solo para monitoreo.
- [ ] `POST /api/video/recording/start` y `.../stop` generan un `.mp4`
      reproducible en `logs/video/` (no corrupto, con audio/video en sync
      si aplica).
- [ ] `POST /api/video/stop` libera el dispositivo correctamente — reabrir
      con `/api/video/start` inmediatamente después no debe fallar por
      dispositivo ocupado.
- [ ] **Balance de blancos anti-magenta**: correr
      `python backend/video_calibrate.py --device 0`, aplicar el preset con
      la tecla `I` (`wb_r 0.75 / wb_g 1.10 / wb_b 0.75`) y confirmar
      visualmente que corrige el tinte magenta característico de la
      EasyCap. Si no corrige del todo, anotar los valores que sí funcionan
      — es un ítem explícito de "corto plazo" en el roadmap.
- [ ] Ajustar brillo/contraste/saturación/gamma con `B/C/S/G`, guardar con
      `W`, y confirmar que `POST /api/video/config` / `GET /api/video/config`
      reflejan los mismos valores guardados en `video_config.json`.

## 4. Pipeline de visión (Fase 2 — v2.6.0)

- [ ] `GET /api/vision/status` y `GET /api/vision/models` responden
      correctamente (detección y segmentación por separado; los `.pt` en
      `models/` aparecen en la lista de su etapa según la convención `-seg`).
- [ ] `POST /api/yolo/config` activa la detección sobre el stream real (no
      solo sobre un video pregrabado): bounding boxes + HUD de latencia
      aparecen embebidos en el frame que llega por WebRTC.
- [ ] `POST /api/segmentation/config` con `focus_mode: "overlay"` dibuja
      contornos amarillos; con `"mask"` y detección activa, verificar en
      escenas con ruido analógico si los falsos positivos bajan respecto a
      detección sola (razón de ser de la etapa — si no aporta, se apaga).
- [ ] **El stream no pierde FPS con la visión activa** (diseño desacoplado
      de v2.6.0): comparar los FPS del player (F2) con visión on/off. El
      overlay puede ir atrasado ≤1 ciclo de inferencia; eso es esperado.
- [ ] Medir con el stream en vivo (panel AI o `/api/vision/status`):
      `latency.vision_fps` y `latency.pipeline_ms` para cada combinación
      (det solo / seg overlay / seg mask + det) — datos pendientes en el
      roadmap; las cifras actuales vienen de frames sintéticos.
- [ ] Verificar el `LatencyGovernor` en vivo: Vmax visible en HUD/panel con
      visión activa; forzar modo `stale` (p. ej. cargar yolov8m en CPU o
      detener la captura) y confirmar que pasa a "HOVER".
- [ ] Con esos números, registrar una recomendación explícita: ¿cascada
      completa, detección sola, o post-proceso sobre el MP4 grabado?
      (decisión pendiente en el roadmap, esta prueba la informa).

## 5. Señal RF / rango (si hay oportunidad de vuelo real)

- [ ] Confirmar visualmente que RSSI/LQ decae de forma esperable con la
      distancia y que el valor reportado por `/api/status` coincide con lo
      que muestra la TX12 en su propia pantalla (cross-check de que el
      parseo CRSF no está desfasado o invirtiendo campos).
- [ ] Si es posible, una prueba de alcance aproximada para contrastar con
      la estimación de ~1.5–2 km del roadmap (RSSI/LQ, no distancia GPS —
      el Mobula8 no trae GPS).

## 6. Regresión general tras la reestructuración v2.5.0

- [ ] Ningún endpoint de la lista completa (~25, ver `elrs_backend.py`)
      devuelve 500 en uso normal durante toda la sesión de pruebas.
- [ ] Cerrar el servidor con Ctrl+C: verificar shutdown limpio (libera
      puerto serial, cierra captura de video, no deja procesos huérfanos).

---

## Salida esperada de esta ronda

Para cada sección, un veredicto: **OK** / **OK con ajuste** (anotar el
ajuste, ej. nuevos valores de `wb_*`) / **falla** (anotar log/repro).
Los hallazgos de "OK con ajuste" o "falla" deben volcarse como entradas
nuevas en `ROADMAP.md` antes de continuar con Fase 3
(`command_injector.py`) — el roadmap ya marca esta validación como
bloqueante para no acumular deuda técnica sobre una base no probada.
