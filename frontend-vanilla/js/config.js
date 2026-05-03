/**
 * Configuration - Customize the telemetry UI
 */

export const CONFIG = {
    // WebSocket connection
    websocket: {
        // Auto-reconnect settings
        reconnectDelay: 3000,  // ms
        maxReconnectAttempts: -1,  // -1 = infinite
        
        // Heartbeat (keep-alive)
        heartbeatInterval: 30000,  // ms
        heartbeatTimeout: 5000  // ms
    },
    
    // Horizon rendering
    horizon: {
        // Rendering
        targetFPS: 60,
        smoothFactor: 0.15,  // Lower = smoother but slower response
        
        // Visual settings
        pitchScale: 3,  // pixels per degree
        pitchLadderStep: 10,  // degrees
        
        // Colors
        skyColor: '#1a8cff',
        groundColor: '#4a2511',
        horizonColor: '#ffff00',
        pitchLineColor: '#ffffff',
        aircraftColor: '#ffff00',
        compassColor: '#808080',
        compassNorthColor: '#ff0000'
    },
    
    // Telemetry display
    telemetry: {
        // Battery thresholds
        batteryWarningPercent: 20,
        batteryCriticalPercent: 10,
        
        // RSSI thresholds (dBm)
        rssiExcellent: -60,
        rssiGood: -80,
        
        // Link Quality thresholds (%)
        lqExcellent: 80,
        lqGood: 50,
        
        // Update rates
        displayUpdateRate: 10,  // Hz (max rate to update DOM)
        
        // Number formatting
        voltageDecimals: 2,
        currentDecimals: 1,
        angleDecimals: 1
    },
    
    // Flight log
    log: {
        maxEntries: 100,
        autoScroll: true,
        timestampFormat: 'HH:MM:SS',  // or 'HH:MM:SS.mmm'
        
        // Log levels to display
        levels: {
            info: true,
            success: true,
            warning: true,
            error: true
        }
    },
    
    // Performance
    performance: {
        // Enable performance monitoring
        enableMonitoring: true,
        
        // Log performance stats to console
        logStats: false,
        logStatsInterval: 10000,  // ms
        
        // Throttle DOM updates
        throttleDOMUpdates: true,
        domUpdateInterval: 100  // ms (10 Hz)
    },
    
    // UI behavior
    ui: {
        // Show/hide elements
        showAttitudeOverlay: true,
        showCompass: true,
        showFlightLog: true,
        
        // Responsive breakpoints
        breakpoints: {
            mobile: 600,
            tablet: 900,
            desktop: 1200
        }
    },
    
    // Development/debugging
    debug: {
        enabled: false,  // Set to true for verbose logging
        logWebSocketMessages: false,
        logTelemetryUpdates: false,
        showFPS: false
    }
};

// Helper to update config at runtime
export function updateConfig(path, value) {
    const keys = path.split('.');
    let obj = CONFIG;
    
    for (let i = 0; i < keys.length - 1; i++) {
        obj = obj[keys[i]];
    }
    
    obj[keys[keys.length - 1]] = value;
    console.log(`[CONFIG] Updated ${path} = ${value}`);
}

// Export as default
export default CONFIG;
