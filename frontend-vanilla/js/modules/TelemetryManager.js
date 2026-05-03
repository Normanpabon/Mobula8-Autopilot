/**
 * TelemetryManager - Central state management for telemetry data
 * 
 * Manages current state and notifies subscribers when data changes.
 * Event-driven architecture for reactive UI updates.
 */

export class TelemetryManager {
    constructor() {
        // Current telemetry state
        this.state = {
            battery: {
                voltage: 0,
                current: 0,
                mah_used: 0,
                percent: 100
            },
            link: {
                rssi1: -120,
                rssi2: 0,
                lq: 0,
                snr: 0,
                active_antenna: 0,
                rf_mode: 0,
                tx_power: 0,
                uplink_rssi: 0,
                uplink_lq: 0,
                uplink_snr: 0
            },
            attitude: {
                pitch: 0,
                roll: 0,
                yaw: 0
            },
            flight_mode: {
                mode: 'DISARMED'
            },
            gps: {
                lat: 0,
                lon: 0,
                alt: 0,
                speed: 0,
                heading: 0,
                sats: 0
            }
        };
        
        // Event subscribers
        this.subscribers = {
            battery: [],
            link: [],
            attitude: [],
            flight_mode: [],
            gps: [],
            '*': []  // Wildcard - notified on any update
        };
        
        // Statistics
        this.stats = {
            framesReceived: 0,
            lastUpdate: null,
            updateRate: 0,  // Hz
            startTime: Date.now()
        };
        
        // Rate calculation
        this._updateTimes = [];
        this._rateInterval = null;
        this._startRateMonitor();
    }
    
    /**
     * Update telemetry data
     * @param {string} type - Type of data (battery, link, attitude, etc)
     * @param {object} data - New data
     */
    update(type, data) {
        if (!this.state.hasOwnProperty(type)) {
            console.warn(`[TelemetryManager] Unknown type: ${type}`);
            return;
        }
        
        // Update state
        this.state[type] = { ...this.state[type], ...data };
        
        // Update stats
        this.stats.framesReceived++;
        this.stats.lastUpdate = Date.now();
        this._updateTimes.push(Date.now());
        
        // Notify subscribers
        this._notify(type, this.state[type]);
    }
    
    /**
     * Subscribe to telemetry updates
     * @param {string} type - Type to subscribe to (or '*' for all)
     * @param {function} callback - Callback function(data)
     * @returns {function} Unsubscribe function
     */
    on(type, callback) {
        if (!this.subscribers.hasOwnProperty(type)) {
            this.subscribers[type] = [];
        }
        
        this.subscribers[type].push(callback);
        
        // Return unsubscribe function
        return () => {
            const index = this.subscribers[type].indexOf(callback);
            if (index > -1) {
                this.subscribers[type].splice(index, 1);
            }
        };
    }
    
    /**
     * Get current state for a specific type
     * @param {string} type - Type of data to get
     * @returns {object} Current state
     */
    get(type) {
        return this.state[type] || null;
    }
    
    /**
     * Get all current state
     * @returns {object} All telemetry data
     */
    getAll() {
        return { ...this.state };
    }
    
    /**
     * Get statistics
     * @returns {object} Stats
     */
    getStats() {
        return {
            ...this.stats,
            uptime: Date.now() - this.stats.startTime
        };
    }
    
    /**
     * Reset all telemetry data to defaults
     */
    reset() {
        this.state = {
            battery: { voltage: 0, current: 0, mah_used: 0, percent: 100 },
            link: { rssi1: -120, rssi2: 0, lq: 0, snr: 0, active_antenna: 0, rf_mode: 0, tx_power: 0, uplink_rssi: 0, uplink_lq: 0, uplink_snr: 0 },
            attitude: { pitch: 0, roll: 0, yaw: 0 },
            flight_mode: { mode: 'DISARMED' },
            gps: { lat: 0, lon: 0, alt: 0, speed: 0, heading: 0, sats: 0 }
        };
        
        this.stats.framesReceived = 0;
        this.stats.lastUpdate = null;
        this._updateTimes = [];
    }
    
    /**
     * Notify subscribers of update
     * @private
     */
    _notify(type, data) {
        // Notify type-specific subscribers
        if (this.subscribers[type]) {
            this.subscribers[type].forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error(`[TelemetryManager] Subscriber error for ${type}:`, error);
                }
            });
        }
        
        // Notify wildcard subscribers
        if (this.subscribers['*']) {
            this.subscribers['*'].forEach(callback => {
                try {
                    callback(type, data);
                } catch (error) {
                    console.error('[TelemetryManager] Wildcard subscriber error:', error);
                }
            });
        }
    }
    
    /**
     * Calculate update rate (Hz)
     * @private
     */
    _startRateMonitor() {
        this._rateInterval = setInterval(() => {
            const now = Date.now();
            const window = 1000; // 1 second window
            
            // Remove old timestamps
            this._updateTimes = this._updateTimes.filter(t => now - t < window);
            
            // Calculate rate
            this.stats.updateRate = this._updateTimes.length;
        }, 1000);
    }
    
    /**
     * Cleanup
     */
    destroy() {
        if (this._rateInterval) {
            clearInterval(this._rateInterval);
        }
        this.subscribers = {};
    }
}
