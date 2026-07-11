/**
 * Utility Functions
 * Common helpers for formatting, math, and conversions
 */

/**
 * Format time as HH:MM:SS
 * @param {Date} date - Date object
 * @returns {string} Formatted time
 */
export function formatTime(date) {
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${hours}:${minutes}:${seconds}`;
}

/**
 * Format timestamp as HH:MM:SS.mmm
 * @param {Date} date - Date object
 * @returns {string} Formatted timestamp with milliseconds
 */
export function formatTimestamp(date) {
    const time = formatTime(date);
    const ms = String(date.getMilliseconds()).padStart(3, '0');
    return `${time}.${ms}`;
}

/**
 * Format number with fixed decimals
 * @param {number} value - Number to format
 * @param {number} decimals - Number of decimal places (default: 2)
 * @returns {string} Formatted number
 */
export function formatNumber(value, decimals = 2) {
    return Number(value).toFixed(decimals);
}

/**
 * Clamp a value between min and max
 * @param {number} value - Value to clamp
 * @param {number} min - Minimum value
 * @param {number} max - Maximum value
 * @returns {number} Clamped value
 */
export function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

/**
 * Linear interpolation between two values
 * @param {number} a - Start value
 * @param {number} b - End value
 * @param {number} t - Interpolation factor (0-1)
 * @returns {number} Interpolated value
 */
export function lerp(a, b, t) {
    return a + (b - a) * clamp(t, 0, 1);
}

/**
 * Map a value from one range to another
 * @param {number} value - Value to map
 * @param {number} inMin - Input range minimum
 * @param {number} inMax - Input range maximum
 * @param {number} outMin - Output range minimum
 * @param {number} outMax - Output range maximum
 * @returns {number} Mapped value
 */
export function mapRange(value, inMin, inMax, outMin, outMax) {
    return ((value - inMin) * (outMax - outMin)) / (inMax - inMin) + outMin;
}

/**
 * Convert degrees to radians
 * @param {number} degrees - Angle in degrees
 * @returns {number} Angle in radians
 */
export function degToRad(degrees) {
    return degrees * (Math.PI / 180);
}

/**
 * Convert radians to degrees
 * @param {number} radians - Angle in radians
 * @returns {number} Angle in degrees
 */
export function radToDeg(radians) {
    return radians * (180 / Math.PI);
}

/**
 * Normalize angle to -180 to 180 range
 * @param {number} angle - Angle in degrees
 * @returns {number} Normalized angle
 */
export function normalizeAngle(angle) {
    while (angle > 180) angle -= 360;
    while (angle < -180) angle += 360;
    return angle;
}

/**
 * Get color based on percentage (green -> yellow -> red)
 * @param {number} percent - Percentage (0-100)
 * @returns {string} CSS color
 */
export function getColorFromPercent(percent) {
    if (percent > 50) return '#00ff88';  // Green
    if (percent > 20) return '#ffcc00';  // Yellow
    return '#ff3b5c';  // Red
}

/**
 * Get color based on RSSI value
 * @param {number} rssi - RSSI in dBm
 * @returns {string} CSS color
 */
export function getColorFromRSSI(rssi) {
    if (rssi > -60) return '#00ff88';  // Excellent
    if (rssi > -80) return '#ffcc00';  // Good
    return '#ff3b5c';  // Poor
}

/**
 * Get color based on Link Quality
 * @param {number} lq - Link quality percentage (0-100)
 * @returns {string} CSS color
 */
export function getColorFromLQ(lq) {
    if (lq > 80) return '#00ff88';  // Excellent
    if (lq > 50) return '#ffcc00';  // Good
    return '#ff3b5c';  // Poor
}

/**
 * Debounce function calls
 * @param {function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {function} Debounced function
 */
export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Throttle function calls
 * @param {function} func - Function to throttle
 * @param {number} limit - Time limit in milliseconds
 * @returns {function} Throttled function
 */
export function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * Request animation frame with fallback
 * @param {function} callback - Animation callback
 * @returns {number} Request ID
 */
export function requestFrame(callback) {
    return window.requestAnimationFrame(callback);
}

/**
 * Cancel animation frame
 * @param {number} id - Request ID
 */
export function cancelFrame(id) {
    window.cancelAnimationFrame(id);
}

/**
 * Check if running on mobile device
 * @returns {boolean} True if mobile
 */
export function isMobile() {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
}

/**
 * Check if running on touch device
 * @returns {boolean} True if touch capable
 */
export function isTouchDevice() {
    return 'ontouchstart' in window || navigator.maxTouchPoints > 0;
}

/**
 * Get canvas 2D context with fallback
 * @param {HTMLCanvasElement} canvas - Canvas element
 * @param {object} options - Context options
 * @returns {CanvasRenderingContext2D} 2D context
 */
export function getCanvas2D(canvas, options = {}) {
    const ctx = canvas.getContext('2d', {
        alpha: true,
        desynchronized: true,  // Better performance
        ...options
    });
    
    if (!ctx) {
        throw new Error('Failed to get 2D context');
    }
    
    return ctx;
}

/**
 * Set canvas size with DPI scaling
 * @param {HTMLCanvasElement} canvas - Canvas element
 * @param {number} width - Logical width
 * @param {number} height - Logical height
 */
export function setCanvasSize(canvas, width, height) {
    const dpr = window.devicePixelRatio || 1;
    
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    
    const ctx = canvas.getContext('2d');
    if (ctx) {
        ctx.scale(dpr, dpr);
    }
}

/**
 * Clear canvas
 * @param {CanvasRenderingContext2D} ctx - Canvas context
 */
export function clearCanvas(ctx) {
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.restore();
}

/**
 * Create smooth gradient
 * @param {CanvasRenderingContext2D} ctx - Canvas context
 * @param {number} x0 - Start X
 * @param {number} y0 - Start Y
 * @param {number} x1 - End X
 * @param {number} y1 - End Y
 * @param {Array} colorStops - Array of {offset, color} objects
 * @returns {CanvasGradient} Gradient
 */
export function createGradient(ctx, x0, y0, x1, y1, colorStops) {
    const gradient = ctx.createLinearGradient(x0, y0, x1, y1);
    colorStops.forEach(stop => {
        gradient.addColorStop(stop.offset, stop.color);
    });
    return gradient;
}
