# Inyección de comandos RC — Fase 3 — Mobula8-Autopilot

Diseño de `backend/command_injector.py` (v2.7.0): cómo el PC envía comandos
RC a la TX12 por USB serial, qué garantías de seguridad tiene, y cuál es la
incógnita de protocolo que solo el hardware puede responder.

Última actualización: 2026-07-11 (v2.7.0).

---

## 1. Qué hace

Cierra el tramo de bajada del lazo de control previsto en Fase 4:

```
telemetría + visión → decisión → [ESTA PIEZA] → TX12 → ELRS → Mobula8
```

El PC construye frames **CRSF RC Channels Packed** (tipo `0x16`: 16 canales
× 11 bits, 22 bytes de payload, CRC8 DVB-S2) y los escribe por el mismo
puerto USB serial por el que ya lee la telemetría (full-duplex; el reader y
el injector comparten el handle `serial_conn` sin estorbarse).

Convención de canales (Betaflight AETR): `1=roll, 2=pitch, 3=throttle,
4=yaw, 5–16=aux`. Valores en microsegundos **988–2012** (1500 = centro);
mapeo a ticks CRSF: `ticks = 992 + (µs − 1500) × 8/5` (172–1811).

## 2. Diseño

### Envío continuo, no comandos sueltos

CRSF es un stream: el receptor espera frames RC a ritmo constante. El
injector corre un **loop de envío a `rate_hz`** (default 50 Hz) que
transmite siempre el último estado de canales. La API/WS solo actualiza ese
estado; no envía frames directamente.

### Deadman switch (la garantía central)

Si no llega **ninguna** actualización de canales en `deadman_ms` (default
500 ms), el loop conmuta a los valores de failsafe hasta el siguiente
comando:

| Canal | Failsafe | Por qué |
|-------|----------|---------|
| throttle (3) | 988 µs (mínimo) | un drone con throttle al centro sube |
| roll/pitch/yaw | 1500 µs (centro) | sin actitud comandada |
| aux 5–16 | 988 µs (abajo) | posición típica de DISARM en aux |

El deadman también aplica **antes del primer comando** (al habilitar, el
injector arranca en failsafe hasta que alguien comande algo) y cubre la
muerte del navegador: el panel de la UI envía a 10 Hz fijos por
`WS /ws/rc`, así que si la pestaña se cierra o la red se cae, en ≤500 ms
los canales vuelven a failsafe.

Nota de alcance: el deadman protege del lado PC. La red de seguridad final
sigue siendo el failsafe del propio ELRS/Betaflight (pérdida de RF ⇒ drop),
que es independiente de este sistema.

### Habilitación con precondiciones

- `POST /api/rc/config {enabled: true}` responde **409** si el serial no
  está conectado.
- Al habilitar, los canales se resetean a failsafe (nunca se retoma un
  estado viejo).
- Deshabilitar detiene el envío por completo (la TX12 vuelve a mandar
  exclusivamente sus propios gimbals).

## 3. La incógnita de protocolo (pendiente de hardware)

**No está confirmado que EdgeTX acepte CRSF de entrada por USB serial en
modo Telem Mirror** — ese modo está documentado como espejo de *salida* de
telemetría. Es el ítem "pendiente de validación de protocolo" del roadmap
desde que se planeó la Fase 3. El plan de validación
(`HARDWARE_VALIDATION.md` §7) prueba, en orden:

1. Frames con dirección `0xEE` (módulo transmisor) — default del injector.
2. `0xEA` (radio) y `0xC8` (FC) — el `sync_byte` es configurable por API
   precisamente para esto.
3. Si la TX12 ignora todo CRSF entrante: **plan B = modo Joystick USB HID**
   de EdgeTX (el PC no inyecta; la radio expone entrenador/joystick). Eso
   invertiría el flujo (la radio lee al PC como joystick virtual, lo que en
   Windows requiere un driver de joystick virtual tipo vJoy) o exigiría un
   módulo ELRS externo en la bahía JR hablando CRSF directo. Decisión para
   cuando haya datos.

Mientras tanto, todo el lado PC (frames, CRC, deadman, API, UI) está
implementado y probado con un serial loopback, de modo que la sesión de
validación con hardware solo tenga que responder la pregunta de protocolo.

## 4. Seguridad operacional (para las pruebas con hardware)

1. **Primera prueba SIN drone encendido**: solo TX12 por USB, observando si
   la radio reacciona (pantalla de canales / mixer) a los frames inyectados.
2. Segunda prueba con el Mobula8 **sin hélices**.
3. Nunca habilitar la inyección con el drone armado y con hélices hasta que
   el deadman esté validado en runtime (checklist §7).
4. El panel RC de la UI muestra el estado del deadman en vivo
   (`OFF` / `FAILSAFE` / `LIVE`) y el contador de frames enviados.

## 5. API

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/rc/status` | Estado: enabled, deadman, canales actuales, frames enviados, serial |
| `POST` | `/api/rc/config` | `enabled`, `rate_hz` (1–250), `deadman_ms` (100–5000), `sync_byte` (`0xEE`/`0xEA`/`0xC8`) |
| `POST` | `/api/rc/channels` | `{"channels": {"throttle": 1600, "1": 1450, ...}}` — alias AETR o índice 1–16, µs |
| `POST` | `/api/rc/center` | Todos los canales a failsafe (posición segura) |
| `WS` | `/ws/rc` | Mismo payload que `/api/rc/channels`, para el envío continuo de la UI/gamepad |

El panel **RC** de la UI usa `WS /ws/rc` a 10 Hz con sliders AETR o un
gamepad (Web Gamepad API, mapeo Mode 2: stick izquierdo throttle/yaw,
derecho roll/pitch).

## 6. Integración prevista con el autopilot (Fase 4)

`autopilot.py` será otro cliente del injector (llamadas directas a
`set_channels()`, no HTTP): produce consignas AETR a su propio ritmo y el
deadman lo cubre igual — si la máquina de estados se cuelga, los canales
caen a failsafe. El límite de velocidad del `LatencyGovernor`
(`VISION_PIPELINE.md` §4) se aplica **antes** de traducir la consigna a µs.
