const port = document.getElementById('serialPort');
const baud = document.getElementById('serialBaud');
const status = document.getElementById('serialStatus');
const error = document.getElementById('serialError');
const connect = document.getElementById('serialConnect');
const disconnect = document.getElementById('serialDisconnect');
const refresh = document.getElementById('serialRefresh');
let busy = false;
let connected = false;
let selectedPort = null;
let os = '';

async function request(url, body) {
    const response = await fetch(url, body === undefined ? {} : {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'No se pudo completar la operación serial');
    return data;
}

function buttons() {
    connect.disabled = busy || !port.value;
    disconnect.disabled = busy || !selectedPort;
    refresh.disabled = busy;
    port.disabled = busy;
    baud.disabled = busy;
}

async function poll() {
    const state = await request('/api/status');
    connected = state.connected;
    selectedPort = state.serial_port;
    const telemetry = connected
        ? ` · ${state.telemetry_active ? 'Telemetría activa' : state.telemetry_state === 'STALE' ? 'Telemetría vencida' : 'Sin telemetría'}`
        : '';
    const counters = connected
        ? ` · ${state.serial_bytes_received ?? 0} bytes · ${state.frames_received ?? 0} muestras · ${state.serial_crc_errors ?? 0} CRC erróneos`
        : '';
    status.textContent = `${os} · ${connected ? `Puerto abierto: ${state.serial_port} @ ${state.baud_rate}` : `${state.serial_state || 'DISCONNECTED'}${state.serial_port ? `: ${state.serial_port}` : ''}`}${telemetry}${counters}${state.serial_error ? ` · ${state.serial_error}` : ''}`;
    buttons();
    window.dispatchEvent(new CustomEvent('serial-status', { detail: state }));
    return state;
}

async function loadPorts() {
    const previous = port.value;
    const data = await request('/api/serial/ports');
    os = data.platform;
    const state = await poll();
    port.replaceChildren(new Option(data.ports.length ? 'Selecciona un puerto' : 'No hay puertos disponibles', ''));
    for (const item of data.ports) {
        port.add(new Option(`${item.device} — ${item.description}`, item.device));
    }
    const selected = previous || state.serial_port;
    if (data.ports.some(item => item.device === selected)) port.value = selected;
    buttons();
}

async function action(fn) {
    busy = true;
    error.textContent = '';
    buttons();
    try { await fn(); }
    catch (err) { error.textContent = err.message; }
    finally {
        try { await poll(); } catch (_) { status.textContent = 'Servidor no disponible'; connected = false; }
        busy = false;
        buttons();
    }
}

refresh.addEventListener('click', () => action(loadPorts));
port.addEventListener('change', buttons);
connect.addEventListener('click', () => action(async () => {
    if (!baud.reportValidity()) return;
    await request('/api/serial/connect', { port: port.value, baud: Number(baud.value) });
}));
disconnect.addEventListener('click', () => action(() => request('/api/serial/disconnect', {})));
action(loadPorts);
// Refrescar el estado permite detectar una extracción física sin cerrar el WebSocket.
setInterval(() => {
    if (!busy) poll().catch(() => {
        connected = false;
        status.textContent = 'Servidor no disponible';
        buttons();
        window.dispatchEvent(new CustomEvent('serial-status', { detail: { connected: false } }));
    });
}, 2000);
