/**
 * ELRS Telemetry UI - Main Application
 * Vanilla JS - Zero dependencies
 */

import { TelemetryManager } from './modules/TelemetryManager.js';
import { HorizonCanvas } from './modules/HorizonCanvas.js';
import { formatTime } from './modules/Utils.js';

const lastClientEvents = new Map();
let clientLoggingEnabled = true;
function reportClientEvent(level, message) {
    if (!clientLoggingEnabled) return;
    const key = `${level}:${message}`;
    const now = Date.now();
    if (now - (lastClientEvents.get(key) || 0) < 10000) return;
    if (lastClientEvents.size > 100) lastClientEvents.clear();
    lastClientEvents.set(key, now);
    fetch('/api/client/events', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({level, message: String(message).slice(0, 2000)}),
        keepalive: true,
    }).catch(() => {});
}
window.reportClientEvent = reportClientEvent;
window.addEventListener('error', (event) => {
    reportClientEvent('error', `Browser error: ${event.message} @ ${event.filename}:${event.lineno}:${event.colno}`);
});
window.addEventListener('unhandledrejection', (event) => {
    reportClientEvent('error', `Unhandled rejection: ${event.reason?.stack || event.reason}`);
});

// ─── Global State ───
let ws = null;
let telemetry = null;
let horizon = null;
let reconnectTimeout = null;
let telemetryActive = false;
window.addEventListener('serial-status', ({ detail }) => {
    telemetryActive = Boolean(detail.telemetry_active);
    if (detail.app_log_level) clientLoggingEnabled = detail.app_log_level !== 'OFF';
    updateConnectionStatus(ws?.readyState === WebSocket.OPEN && telemetryActive ? 'connected' : 'disconnected');
});

// ─── DOM Elements ───
const elements = {
    // Status
    connectionStatus: document.getElementById('connectionStatus'),
    statusText: document.getElementById('statusText'),
    flightMode: document.getElementById('flightMode'),
    
    // Attitude
    pitchValue: document.getElementById('pitchValue'),
    rollValue: document.getElementById('rollValue'),
    yawValue: document.getElementById('yawValue'),
    
    // Battery
    batteryVoltage: document.getElementById('batteryVoltage'),
    batteryCurrent: document.getElementById('batteryCurrent'),
    batteryCapacity: document.getElementById('batteryCapacity'),
    batteryPercent: document.getElementById('batteryPercent'),
    batteryFill: document.getElementById('batteryFill'),
    
    // Link
    linkRSSI: document.getElementById('linkRSSI'),
    linkLQ: document.getElementById('linkLQ'),
    linkSNR: document.getElementById('linkSNR'),
    linkRFMode: document.getElementById('linkRFMode'),
    
    // Log
    logContainer: document.getElementById('logContainer')
};

// ─── WebSocket Connection ───
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    console.log('[WS] Connecting to:', wsUrl);
    addLog('Connecting to telemetry server...', 'info');
    
    try {
        ws = new WebSocket(wsUrl);
        
        ws.onopen = handleWebSocketOpen;
        ws.onmessage = handleWebSocketMessage;
        ws.onerror = handleWebSocketError;
        ws.onclose = handleWebSocketClose;
        
    } catch (error) {
        console.error('[WS] Connection error:', error);
        updateConnectionStatus('disconnected');
        scheduleReconnect();
    }
}

function handleWebSocketOpen() {
    console.log('[WS] Connected');
    updateConnectionStatus(telemetryActive ? 'connected' : 'disconnected');
    addLog('WebSocket connected', 'success');
    
    // Clear reconnect timeout
    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
    }
}

function handleWebSocketMessage(event) {
    try {
        const frame = JSON.parse(event.data);
        
        // Update telemetry state
        telemetry.update(frame.type, frame.data);
        telemetryActive = true;
        updateConnectionStatus('connected');
        
        // Log important events
        if (frame.type === 'flight_mode') {
            addLog(`Mode: ${frame.data.mode}`, 'info');
        }
        
    } catch (error) {
        console.error('[WS] Message parse error:', error);
        reportClientEvent('error', `WebSocket message error: ${error}`);
    }
}

function handleWebSocketError(error) {
    console.error('[WS] Error:', error);
    updateConnectionStatus('disconnected');
}

function handleWebSocketClose() {
    console.log('[WS] Disconnected');
    updateConnectionStatus('disconnected');
    addLog('WebSocket disconnected', 'warning');
    
    // Schedule reconnect
    scheduleReconnect();
}

function scheduleReconnect() {
    if (reconnectTimeout) return;
    
    console.log('[WS] Reconnecting in 3 seconds...');
    reconnectTimeout = setTimeout(() => {
        reconnectTimeout = null;
        connectWebSocket();
    }, 3000);
}

// ─── Connection Status UI ───
function updateConnectionStatus(status) {
    elements.connectionStatus.className = `connection-status ${status}`;
    
    const statusTexts = {
        'connected': 'LIVE',
        'connecting': 'CONNECTING',
        'disconnected': 'OFFLINE'
    };
    
    elements.statusText.textContent = statusTexts[status] || 'UNKNOWN';
}

// ─── UI Updates ───
function updateBatteryUI(data) {
    elements.batteryVoltage.textContent = `${data.voltage.toFixed(2)}V`;
    elements.batteryCurrent.textContent = `${data.current.toFixed(1)}A`;
    elements.batteryCapacity.textContent = `${data.mah_used}mAh`;
    elements.batteryPercent.textContent = `${data.percent}%`;
    
    // Update battery bar
    elements.batteryFill.style.width = `${data.percent}%`;
    
    // Color based on percentage
    let color;
    if (data.percent > 50) {
        color = '#00ff88';  // Green
    } else if (data.percent > 20) {
        color = '#ffcc00';  // Yellow
    } else {
        color = '#ff3b5c';  // Red
    }
    elements.batteryFill.style.background = color;
    
    // Log low battery warning
    if (data.percent < 20 && data.percent > 0) {
        addLog(`⚠ Low battery: ${data.percent}%`, 'warning');
    }
}

function updateLinkUI(data) {
    elements.linkRSSI.textContent = `${data.rssi1}dBm`;
    elements.linkLQ.textContent = `${data.lq}%`;
    elements.linkSNR.textContent = `${data.snr}dB`;
    
    // RF Mode mapping
    const rfModes = {
        0: '4Hz', 1: '25Hz', 2: '50Hz', 3: '100Hz',
        4: '150Hz', 5: '200Hz', 6: '250Hz', 7: '500Hz'
    };
    elements.linkRFMode.textContent = rfModes[data.rf_mode] || data.rf_mode;
    
    // Color RSSI based on signal strength
    let rssiColor;
    if (data.rssi1 > -60) {
        rssiColor = '#00ff88';  // Excellent
    } else if (data.rssi1 > -80) {
        rssiColor = '#ffcc00';  // Good
    } else {
        rssiColor = '#ff3b5c';  // Poor
    }
    elements.linkRSSI.style.color = rssiColor;
    
    // Color LQ based on quality
    let lqColor;
    if (data.lq > 80) {
        lqColor = '#00ff88';
    } else if (data.lq > 50) {
        lqColor = '#ffcc00';
    } else {
        lqColor = '#ff3b5c';
    }
    elements.linkLQ.style.color = lqColor;
}

function updateAttitudeUI(data) {
    elements.pitchValue.textContent = `${data.pitch.toFixed(1)}°`;
    elements.rollValue.textContent = `${data.roll.toFixed(1)}°`;
    elements.yawValue.textContent = `${data.yaw.toFixed(1)}°`;
    
    // Update horizon canvas
    if (horizon) {
        horizon.update(data.pitch, data.roll, data.yaw);
    }
}

function updateFlightModeUI(data) {
    elements.flightMode.textContent = data.mode;
}

// ─── Flight Log ───
const logHistory = [];
const MAX_LOGS = 100;

function addLog(message, level = 'info') {
    const timestamp = formatTime(new Date());
    const entry = { timestamp, message, level };
    
    logHistory.unshift(entry);
    if (logHistory.length > MAX_LOGS) {
        logHistory.pop();
    }
    
    renderLogs();
    reportClientEvent(level === 'success' ? 'info' : level, message);
}

function renderLogs() {
    if (logHistory.length === 0) {
        elements.logContainer.innerHTML = '<div class="log-empty">Waiting for telemetry...</div>';
        return;
    }
    
    const html = logHistory.map(log => `
        <div class="log-entry">
            <span class="log-timestamp">${log.timestamp}</span>
            <span class="log-message ${log.level}">${log.message}</span>
        </div>
    `).join('');
    
    elements.logContainer.innerHTML = html;
}

// ─── Initialization ───
function init() {
    console.log('[APP] Initializing ELRS Telemetry UI');
    
    // Create telemetry manager
    telemetry = new TelemetryManager();
    
    // Create horizon canvas
    try {
        horizon = new HorizonCanvas('horizonCanvas');
        horizon.start();
        console.log('[APP] Horizon canvas initialized');
    } catch (error) {
        console.error('[APP] Failed to initialize horizon:', error);
    }
    
    // Subscribe to telemetry updates
    telemetry.on('battery', updateBatteryUI);
    telemetry.on('link', updateLinkUI);
    telemetry.on('attitude', updateAttitudeUI);
    telemetry.on('flight_mode', (data) => {
        updateFlightModeUI(data);
    });
    
    // Initialize connection status
    updateConnectionStatus('connecting');
    
    // Connect WebSocket
    connectWebSocket();
    
    // Initial log render
    renderLogs();
    
    console.log('[APP] Initialization complete');
}

// ─── Start Application ───
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// ─── Export for debugging ───
window.app = {
    telemetry,
    horizon,
    reconnect: connectWebSocket,
    addLog
};
