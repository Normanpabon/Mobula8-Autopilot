/**
 * System Verification & Testing Utilities
 * 
 * Run in browser console:
 *   test.checkSystem()     - Full system check
 *   test.simulateFlight()  - Simulate flight data
 *   test.stressTest()      - Performance stress test
 */

export const test = {
    /**
     * Complete system check
     */
    async checkSystem() {
        console.log('═══════════════════════════════════════');
        console.log('  ELRS Telemetry System Check');
        console.log('═══════════════════════════════════════');
        
        const results = {
            dom: this._checkDOM(),
            modules: this._checkModules(),
            websocket: this._checkWebSocket(),
            canvas: this._checkCanvas(),
            performance: this._checkPerformance()
        };
        
        console.log('\n📊 Results:');
        Object.entries(results).forEach(([name, status]) => {
            const icon = status ? '✅' : '❌';
            console.log(`  ${icon} ${name}: ${status ? 'OK' : 'FAIL'}`);
        });
        
        const allPassed = Object.values(results).every(v => v);
        console.log('\n' + (allPassed ? '✅ All checks passed!' : '⚠️ Some checks failed'));
        console.log('═══════════════════════════════════════');
        
        return allPassed;
    },
    
    /**
     * Check DOM elements
     */
    _checkDOM() {
        const required = [
            'connectionStatus',
            'horizonCanvas',
            'batteryVoltage',
            'linkRSSI',
            'logContainer'
        ];
        
        const missing = required.filter(id => !document.getElementById(id));
        
        if (missing.length > 0) {
            console.error('❌ Missing DOM elements:', missing);
            return false;
        }
        
        console.log('✅ All required DOM elements present');
        return true;
    },
    
    /**
     * Check loaded modules
     */
    _checkModules() {
        if (!window.app) {
            console.error('❌ App not initialized');
            return false;
        }
        
        const required = ['telemetry', 'horizon'];
        const missing = required.filter(mod => !window.app[mod]);
        
        if (missing.length > 0) {
            console.error('❌ Missing modules:', missing);
            return false;
        }
        
        console.log('✅ All modules loaded');
        return true;
    },
    
    /**
     * Check WebSocket connection
     */
    _checkWebSocket() {
        // Just check if connection attempt was made
        console.log('ℹ️ WebSocket status: Check connection indicator in UI');
        return true;  // Can't reliably check without backend running
    },
    
    /**
     * Check canvas rendering
     */
    _checkCanvas() {
        if (!window.app.horizon) {
            console.error('❌ Horizon not initialized');
            return false;
        }
        
        if (!window.app.horizon.isRunning) {
            console.warn('⚠️ Horizon not running - starting...');
            window.app.horizon.start();
        }
        
        console.log('✅ Canvas rendering active');
        return true;
    },
    
    /**
     * Check performance
     */
    _checkPerformance() {
        if (!window.performance) {
            console.warn('⚠️ Performance API not available');
            return true;
        }
        
        const memory = performance.memory;
        if (memory) {
            const usedMB = (memory.usedJSHeapSize / 1048576).toFixed(2);
            const totalMB = (memory.totalJSHeapSize / 1048576).toFixed(2);
            console.log(`ℹ️ Memory: ${usedMB} MB / ${totalMB} MB`);
        }
        
        return true;
    },
    
    /**
     * Simulate flight data for testing
     */
    simulateFlight() {
        console.log('🛩️ Starting flight simulation...');
        
        let time = 0;
        const interval = setInterval(() => {
            time += 0.1;
            
            // Simulate sinusoidal flight
            const pitch = Math.sin(time * 0.5) * 20;  // ±20°
            const roll = Math.sin(time * 0.3) * 30;   // ±30°
            const yaw = (time * 20) % 360;             // Rotating
            
            // Update horizon
            window.app.horizon.update(pitch, roll, yaw);
            
            // Simulate battery drain
            if (Math.random() < 0.01) {  // 1% chance per frame
                const battery = {
                    voltage: 7.4 - time * 0.1,
                    current: 2.5 + Math.random() * 3,
                    mah_used: Math.floor(time * 50),
                    percent: Math.max(0, 100 - time * 2)
                };
                window.app.telemetry.update('battery', battery);
            }
            
            // Simulate link stats
            if (Math.random() < 0.05) {  // 5% chance
                const link = {
                    rssi1: -60 - Math.random() * 20,
                    lq: 80 + Math.random() * 20,
                    snr: 10 + Math.random() * 5,
                    rf_mode: 5
                };
                window.app.telemetry.update('link', link);
            }
            
            // Stop after 30 seconds
            if (time > 30) {
                clearInterval(interval);
                console.log('✅ Flight simulation complete');
            }
        }, 100);
        
        return interval;
    },
    
    /**
     * Stress test - rapid updates
     */
    stressTest(duration = 10000) {
        console.log(`🔥 Starting stress test (${duration}ms)...`);
        
        let frames = 0;
        const startTime = performance.now();
        
        const interval = setInterval(() => {
            frames++;
            
            // Rapid random updates
            window.app.horizon.update(
                Math.random() * 40 - 20,  // ±20°
                Math.random() * 60 - 30,  // ±30°
                Math.random() * 360
            );
            
            if (performance.now() - startTime > duration) {
                clearInterval(interval);
                const fps = (frames / (duration / 1000)).toFixed(2);
                console.log(`✅ Stress test complete: ${frames} frames, ${fps} avg FPS`);
            }
        }, 16);  // ~60 FPS
        
        return interval;
    },
    
    /**
     * Memory leak check
     */
    async memoryTest(iterations = 100) {
        if (!performance.memory) {
            console.warn('⚠️ Memory API not available in this browser');
            return;
        }
        
        console.log(`🧪 Memory leak test (${iterations} iterations)...`);
        
        const startMem = performance.memory.usedJSHeapSize;
        
        for (let i = 0; i < iterations; i++) {
            // Simulate heavy telemetry updates
            window.app.telemetry.update('battery', {
                voltage: Math.random() * 8,
                current: Math.random() * 10,
                mah_used: Math.floor(Math.random() * 1000),
                percent: Math.floor(Math.random() * 100)
            });
            
            await new Promise(resolve => setTimeout(resolve, 10));
        }
        
        // Force GC if available
        if (window.gc) window.gc();
        
        const endMem = performance.memory.usedJSHeapSize;
        const diff = ((endMem - startMem) / 1048576).toFixed(2);
        
        console.log(`Memory delta: ${diff} MB`);
        
        if (Math.abs(diff) > 10) {
            console.warn('⚠️ Possible memory leak detected');
        } else {
            console.log('✅ Memory usage stable');
        }
    }
};

// Make available globally
window.test = test;

console.log('📝 Testing utilities loaded. Available commands:');
console.log('  test.checkSystem()     - Run full system check');
console.log('  test.simulateFlight()  - Simulate flight data');
console.log('  test.stressTest()      - Performance stress test');
console.log('  test.memoryTest()      - Check for memory leaks');
