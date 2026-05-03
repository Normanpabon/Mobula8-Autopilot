/**
 * PerformanceMonitor - Real-time latency and FPS monitoring
 * 
 * Displays performance metrics in UI for diagnostics
 */

export class PerformanceMonitor {
    constructor() {
        this.enabled = false;
        this.metrics = {
            fps: 0,
            latency: 0,
            wsLatency: 0,
            frameCount: 0,
            lastFrameTime: 0,
            updateRate: 0
        };
        
        this.frameTimes = [];
        this.latencyMeasurements = [];
        this.updateTimes = [];
        
        this.overlay = null;
        this.updateInterval = null;
    }
    
    /**
     * Enable performance monitoring with UI overlay
     */
    enable() {
        if (this.enabled) return;
        
        this.enabled = true;
        this._createOverlay();
        this._startMonitoring();
        
        console.log('[PerfMonitor] Enabled');
    }
    
    /**
     * Disable monitoring
     */
    disable() {
        if (!this.enabled) return;
        
        this.enabled = false;
        if (this.overlay) {
            this.overlay.remove();
            this.overlay = null;
        }
        
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
        
        console.log('[PerfMonitor] Disabled');
    }
    
    /**
     * Record frame render
     */
    recordFrame() {
        if (!this.enabled) return;
        
        const now = performance.now();
        
        if (this.metrics.lastFrameTime > 0) {
            const frameDelta = now - this.metrics.lastFrameTime;
            this.frameTimes.push(frameDelta);
            
            // Keep last 60 frames
            if (this.frameTimes.length > 60) {
                this.frameTimes.shift();
            }
            
            // Calculate FPS
            const avgFrameTime = this.frameTimes.reduce((a, b) => a + b, 0) / this.frameTimes.length;
            this.metrics.fps = Math.round(1000 / avgFrameTime);
        }
        
        this.metrics.lastFrameTime = now;
        this.metrics.frameCount++;
    }
    
    /**
     * Record telemetry update latency
     * @param {number} sentTimestamp - When data was sent from drone (ms)
     */
    recordLatency(sentTimestamp) {
        if (!this.enabled) return;
        
        const now = performance.now();
        const latency = now - sentTimestamp;
        
        this.latencyMeasurements.push(latency);
        
        // Keep last 30 measurements
        if (this.latencyMeasurements.length > 30) {
            this.latencyMeasurements.shift();
        }
        
        // Calculate average latency
        this.metrics.latency = Math.round(
            this.latencyMeasurements.reduce((a, b) => a + b, 0) / this.latencyMeasurements.length
        );
    }
    
    /**
     * Record WebSocket message received
     */
    recordUpdate() {
        if (!this.enabled) return;
        
        const now = performance.now();
        this.updateTimes.push(now);
        
        // Keep last 1 second of updates
        const oneSecondAgo = now - 1000;
        this.updateTimes = this.updateTimes.filter(t => t > oneSecondAgo);
        
        this.metrics.updateRate = this.updateTimes.length;
    }
    
    /**
     * Create performance overlay
     * @private
     */
    _createOverlay() {
        this.overlay = document.createElement('div');
        this.overlay.id = 'perf-monitor';
        this.overlay.style.cssText = `
            position: fixed;
            top: 70px;
            right: 10px;
            background: rgba(0, 0, 0, 0.8);
            color: #0f0;
            font-family: monospace;
            font-size: 12px;
            padding: 10px;
            border: 1px solid #0f0;
            border-radius: 4px;
            z-index: 10000;
            min-width: 200px;
        `;
        
        document.body.appendChild(this.overlay);
    }
    
    /**
     * Start monitoring loop
     * @private
     */
    _startMonitoring() {
        this.updateInterval = setInterval(() => {
            this._updateOverlay();
        }, 100);  // Update display 10x per second
    }
    
    /**
     * Update overlay display
     * @private
     */
    _updateOverlay() {
        if (!this.overlay) return;
        
        const fpsColor = this.metrics.fps >= 55 ? '#0f0' : this.metrics.fps >= 30 ? '#ff0' : '#f00';
        const latencyColor = this.metrics.latency <= 100 ? '#0f0' : this.metrics.latency <= 500 ? '#ff0' : '#f00';
        const updateColor = this.metrics.updateRate >= 10 ? '#0f0' : this.metrics.updateRate >= 5 ? '#ff0' : '#f00';
        
        this.overlay.innerHTML = `
            <div style="font-weight: bold; margin-bottom: 5px; color: #0ff;">⚡ PERFORMANCE</div>
            <div>FPS: <span style="color: ${fpsColor}">${this.metrics.fps}</span></div>
            <div>Latency: <span style="color: ${latencyColor}">${this.metrics.latency}ms</span></div>
            <div>Update rate: <span style="color: ${updateColor}">${this.metrics.updateRate} Hz</span></div>
            <div>Frames: ${this.metrics.frameCount}</div>
            <div style="margin-top: 5px; font-size: 10px; color: #888;">
                Press F2 to toggle
            </div>
        `;
    }
    
    /**
     * Get current metrics
     */
    getMetrics() {
        return { ...this.metrics };
    }
}

// Create global instance
export const perfMonitor = new PerformanceMonitor();

// Toggle with F2 key
document.addEventListener('keydown', (e) => {
    if (e.key === 'F2') {
        if (perfMonitor.enabled) {
            perfMonitor.disable();
        } else {
            perfMonitor.enable();
        }
    }
});

console.log('[PerfMonitor] Loaded. Press F2 to toggle performance overlay.');
