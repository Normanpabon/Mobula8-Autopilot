# Inyección de comandos RC — Fase 3 — Mobula8-Autopilot

Diseño de `backend/command_injector.py` (v2.7.0): cómo el PC envía comandos
RC a la TX12 por USB serial, qué garantías de seguridad tiene, y cuál es la
incógnita de protocolo que solo el hardware puede responder.

Última revisión: 2026-09-22. Selección y reconexión serial centralizadas en
`SerialManager`. El contrato RC ahora requiere adquisición explícita,
propietario y época; los clientes anteriores deben actualizarse.
Las pruebas automatizadas no validan la entrada física de la TX12.

---

## 1. Qué hace

Cierra el tramo de bajada del lazo de control previsto en Fase 4:

```
telemetría + visión → decisión → [ESTA PIEZA] → TX12 → ELRS → Mobula8
```

El PC construye frames **CRSF RC Channels Packed** (tipo `0x16`: 16 canales
× 11 bits, 22 bytes de payload, CRC8 DVB-S2) y los escribe por el mismo
puerto USB serial por el que ya lee la telemetría (full-duplex; el gestor
es el único dueño del puerto y ejecuta las lecturas y escrituras).

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
500 ms, reloj monotónico), se invalidan el propietario, la época y los
valores almacenados. El loop transmite failsafe hasta adquirir de nuevo:

| Canal | Failsafe | Por qué |
|-------|----------|---------|
| throttle (3) | 988 µs (mínimo) | un drone con throttle al centro sube |
| roll/pitch/yaw | 1500 µs (centro) | sin actitud comandada |
| aux 5–16 | 988 µs (abajo) | posición típica de DISARM en aux |

El deadman también aplica **antes del primer comando** (al habilitar, el
injector arranca en failsafe hasta que alguien comande algo) y cubre la
muerte del navegador: el panel de la UI envía a 10 Hz fijos por
`WS /ws/rc`, así que si la pestaña se cierra o la red se cae, al superar
500 ms más el periodo de envío y el jitter los canales
transmitidos pasan a failsafe, mientras el proceso y su event loop sigan
funcionando. No es una garantía de tiempo real.

**Correcciones 2026-09-22:** desconectar el gamepad centra y revoca el
control. Cerrar el WebSocket propietario revoca la época y solicita un
frame de failsafe inmediatamente. El timeout borra las consignas; ningún
comando parcial ni token anterior puede reactivarlas. Los comandos se
validan completos antes de modificar el estado, rechazando NaN/infinito.
La UI requiere deshabilitar/habilitar RC después de perder el control.

Nota de alcance: el deadman protege del lado PC. La red de seguridad final
sigue siendo el failsafe del propio ELRS/Betaflight (pérdida de RF ⇒ drop),
que es independiente de este sistema.

### Habilitación con precondiciones

- `POST /api/rc/config {enabled: true}` responde **409** si el serial no
  está conectado.
- Al habilitar, los canales se resetean a failsafe (nunca se retoma un
  estado viejo).
- Deshabilitar detiene el envío por completo. La recuperación de mando por
  los gimbals depende de la ruta de entrada elegida y debe verificarse;
  detener el envío por sí solo no acredita esa recuperación.

## 3. La incógnita de protocolo (pendiente de hardware)

**No está confirmado que EdgeTX acepte CRSF de entrada por USB serial en
modo Telem Mirror** — ese modo está documentado como espejo de *salida* de
telemetría. Es el ítem "pendiente de validación de protocolo" del roadmap
desde que se planeó la Fase 3. El plan de validación
([`PLAN_ACCION.md`](PLAN_ACCION.md)) prueba, en orden:

1. Frames con dirección `0xEE` (módulo transmisor) — default del injector.
2. `0xEA` (radio) y `0xC8` (FC) — el `sync_byte` es configurable por API
   precisamente para esto.
3. Si el firmware no implementa entrada RC por VCP, elegir otra ruta:
   adaptador hacia una entrada trainer compatible con la radio (PPM/SBUS,
   según hardware), o interfaz CRSF con un módulo ELRS externo. Ambas
   requieren diseño y validación de niveles eléctricos, prioridad de mando
   y failsafe antes de conectarlas.

**Corrección del plan B anterior:** USB Joystick HID expone la radio como
mando al PC; no permite inyectar canales del PC hacia la radio. Un joystick
virtual en Linux/Windows no invierte esa dirección. Referencias oficiales:
[hardware/Telem Mirror](https://manual.edgetx.org/v2.11/bw-radios/radio-settings/hardware)
y [joystick](https://manual.edgetx.org/edgetx-how-to/configure-advanced-joystick-with-edgetx).
Cambiar la dirección CRSF no agrega soporte de entrada al firmware.

El lado PC está implementado y el historial reporta pruebas con loopback.
La revisión actual verificó frames/CRC y timeout con una salida simulada;
protocolo, recuperación de mando y seguridad con hardware siguen pendientes.

## 4. Seguridad operacional (para las pruebas con hardware)

1. **Primera prueba SIN drone encendido**: solo TX12 por USB, observando si
   la radio reacciona (pantalla de canales / mixer) a los frames inyectados.
2. Segunda prueba con el Mobula8 **sin hélices**.
3. Nunca habilitar la inyección con el drone armado y con hélices hasta que
   el deadman esté validado en banco (ver `PLAN_ACCION.md`).
4. El panel RC de la UI muestra el estado del deadman en vivo
   (`OFF` / `FAILSAFE` / `LIVE`) y el contador de frames enviados.

## 5. API

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/rc/status` | Estado: enabled, deadman, canales actuales, frames enviados, serial |
| `POST` | `/api/rc/config` | `enabled`, `rate_hz` (1–250), `deadman_ms` (100–5000), `sync_byte` (`0xEE`/`0xEA`/`0xC8`) |
| `POST` | `/api/rc/acquire` | Estado completo de 16 canales con throttle=988; devuelve `epoch`; requiere RC habilitado y sin propietario activo |
| `POST` | `/api/rc/channels` | `{"epoch": "token", "channels": {"1": 1500, ... , "16": 988}}` — requiere los 16 canales; admite alias AETR sin duplicados |
| `POST` | `/api/rc/center` | Todos los canales a failsafe (posición segura) |
| `WS` | `/ws/rc` | Primero `{"action":"acquire","channels":{...16 canales...}}`; luego comandos con el `epoch` recibido; propietario ligado al socket |

El panel **RC** de la UI usa `WS /ws/rc` a 10 Hz con sliders AETR o un
gamepad (Web Gamepad API, mapeo Mode 2: stick izquierdo throttle/yaw,
derecho roll/pitch).

## 6. Integración prevista con el autopilot (Fase 4)

`autopilot.py` será otro cliente del injector (llamadas directas a
`acquire()` y `set_channels(channels, owner, epoch)`, no HTTP): produce estados completos a su propio ritmo y el
deadman lo cubre igual — si la máquina de estados se cuelga, los canales
caen a failsafe. El límite de velocidad del `LatencyGovernor`
(`VISION_PIPELINE.md` §4) se aplica **antes** de traducir la consigna a µs.
