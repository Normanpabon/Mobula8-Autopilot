/**
 * HorizonCanvas - Artificial Horizon using Canvas 2D API
 * 
 * Renders a real-time artificial horizon with:
 * - Sky/Ground with pitch/roll rotation
 * - Pitch ladder (lines every 10°)
 * - Fixed aircraft symbol
 * - Rotating compass for yaw/heading
 * - 60fps smooth rendering
 * 
 * Zero dependencies - Pure Canvas 2D
 */

import { degToRad, setCanvasSize, clearCanvas } from './Utils.js';

export class HorizonCanvas {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) {
            throw new Error(`Canvas element #${canvasId} not found`);
        }
        
        this.ctx = this.canvas.getContext('2d', {
            alpha: false,
            desynchronized: true  // Better performance
        });
        
        // Current attitude
        this.pitch = 0;  // degrees
        this.roll = 0;   // degrees
        this.yaw = 0;    // degrees
        
        // Target attitude (for smooth interpolation)
        this.targetPitch = 0;
        this.targetRoll = 0;
        this.targetYaw = 0;
        
        // Rendering state
        this.animationId = null;
        this.lastFrameTime = 0;
        this.isRunning = false;
        
        // Canvas dimensions
        this.width = 0;
        this.height = 0;
        this.centerX = 0;
        this.centerY = 0;
        
        // Colors
        this.colors = {
            sky: '#1a8cff',
            ground: '#4a2511',
            horizon: '#ffff00',
            pitchLine: '#ffffff',
            aircraft: '#ffff00',
            compass: '#808080',
            compassN: '#ff0000',
            compassText: '#ffffff'
        };
        
        // Initialize
        this._setupCanvas();
        this._setupResizeObserver();
        
        console.log('[HorizonCanvas] Initialized');
    }
    
    /**
     * Setup canvas with proper DPI scaling
     * @private
     */
    _setupCanvas() {
        const rect = this.canvas.getBoundingClientRect();
        this.width = rect.width;
        this.height = rect.height;
        this.centerX = this.width / 2;
        this.centerY = this.height / 2;
        
        setCanvasSize(this.canvas, this.width, this.height);
    }
    
    /**
     * Setup resize observer for responsive canvas
     * @private
     */
    _setupResizeObserver() {
        const resizeObserver = new ResizeObserver(() => {
            this._setupCanvas();
        });
        resizeObserver.observe(this.canvas);
    }
    
    /**
     * Update attitude values
     * @param {number} pitch - Pitch in degrees
     * @param {number} roll - Roll in degrees
     * @param {number} yaw - Yaw in degrees
     */
    update(pitch, roll, yaw) {
        this.targetPitch = pitch;
        this.targetRoll = roll;
        this.targetYaw = yaw;
    }
    
    /**
     * Start rendering loop
     */
    start() {
        if (this.isRunning) return;
        
        this.isRunning = true;
        this.lastFrameTime = performance.now();
        this._renderLoop();
        
        console.log('[HorizonCanvas] Started rendering');
    }
    
    /**
     * Stop rendering loop
     */
    stop() {
        this.isRunning = false;
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        
        console.log('[HorizonCanvas] Stopped rendering');
    }
    
    /**
     * Main rendering loop (60fps)
     * @private
     */
    _renderLoop() {
        if (!this.isRunning) return;
        
        const now = performance.now();
        const deltaTime = (now - this.lastFrameTime) / 1000; // seconds
        this.lastFrameTime = now;
        
        // Smooth interpolation (exponential smoothing)
        const smoothFactor = 0.15;
        this.pitch += (this.targetPitch - this.pitch) * smoothFactor;
        this.roll += (this.targetRoll - this.roll) * smoothFactor;
        this.yaw += (this.targetYaw - this.yaw) * smoothFactor;
        
        // Render frame
        this._render();
        
        // Schedule next frame
        this.animationId = requestAnimationFrame(() => this._renderLoop());
    }
    
    /**
     * Render complete horizon
     * @private
     */
    _render() {
        // Clear canvas
        clearCanvas(this.ctx);
        
        // Draw horizon (sky/ground with rotation)
        this._drawHorizon();
        
        // Draw pitch ladder
        this._drawPitchLadder();
        
        // Draw aircraft symbol (fixed)
        this._drawAircraft();
        
        // Draw compass
        this._drawCompass();
    }
    
    /**
     * Draw sky and ground with pitch/roll rotation
     * @private
     */
    _drawHorizon() {
        const ctx = this.ctx;
        
        ctx.save();
        ctx.translate(this.centerX, this.centerY);
        ctx.rotate(degToRad(-this.roll));
        
        // Calculate pitch offset (pixels per degree)
        const pitchScale = 3; // pixels per degree
        const pitchOffset = this.pitch * pitchScale;
        
        // Draw sky (top half)
        ctx.fillStyle = this.colors.sky;
        ctx.fillRect(-this.width, -this.height - pitchOffset, this.width * 2, this.height * 2);
        
        // Draw ground (bottom half)
        ctx.fillStyle = this.colors.ground;
        ctx.fillRect(-this.width, -pitchOffset, this.width * 2, this.height * 2);
        
        // Draw horizon line
        ctx.strokeStyle = this.colors.horizon;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(-this.width, -pitchOffset);
        ctx.lineTo(this.width, -pitchOffset);
        ctx.stroke();
        
        ctx.restore();
    }
    
    /**
     * Draw pitch ladder (lines every 10 degrees)
     * @private
     */
    _drawPitchLadder() {
        const ctx = this.ctx;
        const pitchScale = 3; // pixels per degree
        
        ctx.save();
        ctx.translate(this.centerX, this.centerY);
        ctx.rotate(degToRad(-this.roll));
        
        // Draw pitch lines from -90° to +90° every 10°
        for (let angle = -90; angle <= 90; angle += 10) {
            if (angle === 0) continue; // Skip horizon (already drawn)
            
            const y = (this.pitch - angle) * pitchScale;
            
            // Only draw if visible
            if (Math.abs(y) > this.height / 2 + 50) continue;
            
            // Line length based on angle
            const lineLength = Math.abs(angle) % 30 === 0 ? 60 : 40;
            
            ctx.strokeStyle = this.colors.pitchLine;
            ctx.lineWidth = angle % 30 === 0 ? 2 : 1.5;
            
            // Draw line
            ctx.beginPath();
            ctx.moveTo(-lineLength, -y);
            ctx.lineTo(lineLength, -y);
            ctx.stroke();
            
            // Draw angle text
            if (Math.abs(angle) % 30 === 0 && angle !== 0) {
                ctx.save();
                ctx.rotate(degToRad(this.roll)); // Un-rotate text
                ctx.fillStyle = this.colors.pitchLine;
                ctx.font = '12px monospace';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(`${Math.abs(angle)}`, -lineLength - 20, -y);
                ctx.fillText(`${Math.abs(angle)}`, lineLength + 20, -y);
                ctx.restore();
            }
        }
        
        ctx.restore();
    }
    
    /**
     * Draw aircraft symbol (fixed in center)
     * @private
     */
    _drawAircraft() {
        const ctx = this.ctx;
        
        ctx.save();
        ctx.translate(this.centerX, this.centerY);
        
        ctx.strokeStyle = this.colors.aircraft;
        ctx.fillStyle = this.colors.aircraft;
        ctx.lineWidth = 3;
        
        // Center dot
        ctx.beginPath();
        ctx.arc(0, 0, 4, 0, Math.PI * 2);
        ctx.fill();
        
        // Left wing
        ctx.beginPath();
        ctx.moveTo(-50, 0);
        ctx.lineTo(-10, 0);
        ctx.stroke();
        
        // Left winglet
        ctx.beginPath();
        ctx.moveTo(-50, 0);
        ctx.lineTo(-50, 8);
        ctx.stroke();
        
        // Right wing
        ctx.beginPath();
        ctx.moveTo(10, 0);
        ctx.lineTo(50, 0);
        ctx.stroke();
        
        // Right winglet
        ctx.beginPath();
        ctx.moveTo(50, 0);
        ctx.lineTo(50, 8);
        ctx.stroke();
        
        ctx.restore();
    }
    
    /**
     * Draw compass (rotating with yaw)
     * @private
     */
    _drawCompass() {
        const ctx = this.ctx;
        const compassY = this.height - 60;
        const radius = 40;
        
        ctx.save();
        ctx.translate(this.centerX, compassY);
        
        // Compass circle background
        ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
        ctx.beginPath();
        ctx.arc(0, 0, radius + 5, 0, Math.PI * 2);
        ctx.fill();
        
        // Rotate based on yaw
        ctx.rotate(degToRad(-this.yaw));
        
        // Draw compass circle
        ctx.strokeStyle = this.colors.compass;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.stroke();
        
        // Draw cardinal directions
        const cardinals = [
            { angle: 0, label: 'N', color: this.colors.compassN },
            { angle: 90, label: 'E', color: this.colors.compassText },
            { angle: 180, label: 'S', color: this.colors.compassText },
            { angle: 270, label: 'W', color: this.colors.compassText }
        ];
        
        cardinals.forEach(({ angle, label, color }) => {
            const rad = degToRad(angle);
            const x = Math.sin(rad) * (radius - 10);
            const y = -Math.cos(rad) * (radius - 10);
            
            ctx.save();
            ctx.rotate(degToRad(this.yaw)); // Un-rotate text
            ctx.fillStyle = color;
            ctx.font = 'bold 14px monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, x, y);
            ctx.restore();
        });
        
        // Draw tick marks every 30 degrees
        for (let i = 0; i < 12; i++) {
            const angle = i * 30;
            const rad = degToRad(angle);
            const x1 = Math.sin(rad) * (radius - 5);
            const y1 = -Math.cos(rad) * (radius - 5);
            const x2 = Math.sin(rad) * radius;
            const y2 = -Math.cos(rad) * radius;
            
            ctx.strokeStyle = this.colors.compass;
            ctx.lineWidth = angle % 90 === 0 ? 2 : 1;
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.stroke();
        }
        
        ctx.restore();
        
        // Draw heading indicator (fixed arrow pointing up)
        ctx.save();
        ctx.translate(this.centerX, compassY);
        ctx.fillStyle = this.colors.aircraft;
        ctx.beginPath();
        ctx.moveTo(0, -radius - 15);
        ctx.lineTo(-5, -radius - 8);
        ctx.lineTo(5, -radius - 8);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
        
        // Draw numeric heading
        ctx.save();
        ctx.fillStyle = this.colors.compassText;
        ctx.font = 'bold 16px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const heading = Math.round((this.yaw + 360) % 360);
        ctx.fillText(`${heading.toString().padStart(3, '0')}°`, this.centerX, compassY + radius + 10);
        ctx.restore();
    }
    
    /**
     * Cleanup
     */
    destroy() {
        this.stop();
    }
}
