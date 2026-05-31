/**
 * VideoPlayer — Cliente WebRTC para el stream FPV
 *
 * Maneja la señalización WebRTC con el backend (aiortc),
 * la reconexión automática y los controles de grabación.
 */

export class VideoPlayer {
    /**
     * @param {HTMLVideoElement} videoEl  - Elemento <video> donde mostrar el stream
     * @param {object}           options
     * @param {string}  options.offerUrl        - URL del endpoint /offer  (default: /offer)
     * @param {string}  options.startUrl        - URL del endpoint /api/video/start
     * @param {string}  options.stopUrl         - URL del endpoint /api/video/stop
     * @param {string}  options.devicesUrl      - URL del endpoint /api/video/devices
     * @param {string}  options.statusUrl       - URL del endpoint /api/video/status
     * @param {string}  options.recStartUrl     - URL para iniciar grabación
     * @param {string}  options.recStopUrl      - URL para detener grabación
     * @param {Function} options.onStateChange  - Callback de cambio de estado
     * @param {Function} options.onError        - Callback de error
     */
    constructor(videoEl, options = {}) {
        this._video  = videoEl;
        this._opts   = {
            offerUrl:   '/offer',
            startUrl:   '/api/video/start',
            stopUrl:    '/api/video/stop',
            devicesUrl: '/api/video/devices',
            statusUrl:  '/api/video/status',
            recStartUrl:'/api/video/recording/start',
            recStopUrl: '/api/video/recording/stop',
            onStateChange: () => {},
            onError:       () => {},
            ...options,
        };

        this._pc          = null;   // RTCPeerConnection
        this._peerId      = null;
        this._state       = 'idle'; // idle | connecting | connected | error | stopped
        this._recording   = false;
        this._reconnectT  = null;
        this._reconnects  = 0;

        // Configuración WebRTC
        this._rtcConfig = {
            iceServers: [
                // Solo ICE local (LAN), sin STUN/TURN necesario
                { urls: 'stun:stun.l.google.com:19302' }
            ],
            iceTransportPolicy: 'all',
        };
    }

    // ── API pública ──────────────────────────────────────────

    /** Lista los dispositivos de captura disponibles */
    async getDevices() {
        const r    = await fetch(this._opts.devicesUrl);
        const data = await r.json();
        return data.devices || [];
    }

    /** Estado actual del servidor (capture + recording + webrtc) */
    async getServerStatus() {
        const r = await fetch(this._opts.statusUrl);
        return r.json();
    }

    /**
     * Inicia la captura en el servidor y luego conecta WebRTC.
     * @param {object} captureOptions - { device_id, width, height, fps }
     */
    async connect(captureOptions = {}) {
        this._setState('connecting');
        this._reconnects = 0;

        try {
            // 1. Decirle al backend que abra la capturadora
            const startResp = await fetch(this._opts.startUrl, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    device_id: captureOptions.device_id ?? 0,
                    width:     captureOptions.width     ?? 1280,
                    height:    captureOptions.height    ?? 720,
                    fps:       captureOptions.fps       ?? 30,
                }),
            });

            if (!startResp.ok) {
                const err = await startResp.json();
                throw new Error(err.error || 'Error iniciando captura');
            }

            // 2. Crear conexión WebRTC y obtener stream
            await this._createPeerConnection();

        } catch (err) {
            console.error('[VideoPlayer] connect error:', err);
            this._setState('error');
            this._opts.onError(err.message);
            this._scheduleReconnect(captureOptions);
        }
    }

    /** Desconecta el stream y detiene la captura en el servidor */
    async disconnect() {
        this._clearReconnect();
        await this._closePeer();

        try {
            await fetch(this._opts.stopUrl, { method: 'POST' });
        } catch (_) {}

        this._setState('idle');
    }

    /** Inicia grabación en el servidor */
    async startRecording() {
        const r    = await fetch(this._opts.recStartUrl, { method: 'POST' });
        const data = await r.json();
        if (data.recording) {
            this._recording = true;
            this._setState(this._state); // refresh callbacks
        }
        return data;
    }

    /** Detiene la grabación */
    async stopRecording() {
        const r    = await fetch(this._opts.recStopUrl, { method: 'POST' });
        const data = await r.json();
        this._recording = false;
        this._setState(this._state);
        return data;
    }

    get state()     { return this._state; }
    get recording() { return this._recording; }
    get connected() { return this._state === 'connected'; }

    // ── Internals ────────────────────────────────────────────

    async _createPeerConnection() {
        // Cerrar conexión previa si existe
        await this._closePeer();

        this._peerId = `peer_${Date.now()}`;
        this._pc     = new RTCPeerConnection(this._rtcConfig);

        // Recibir stream del servidor
        this._pc.ontrack = (event) => {
            if (event.streams && event.streams[0]) {
                console.log('[VideoPlayer] Stream recibido');
                this._video.srcObject = event.streams[0];
                this._video.play().catch(e => console.warn('[VideoPlayer] play():', e));
                this._setState('connected');
                this._reconnects = 0;
            }
        };

        // ICE connection state
        this._pc.oniceconnectionstatechange = () => {
            const s = this._pc?.iceConnectionState;
            console.log('[VideoPlayer] ICE state:', s);
            if (s === 'failed' || s === 'disconnected') {
                this._setState('error');
                this._opts.onError('ICE connection failed');
            }
        };

        // Añadir transceiver de video (solo recibir, sin enviar)
        this._pc.addTransceiver('video', { direction: 'recvonly' });

        // Crear SDP offer
        const offer = await this._pc.createOffer();
        await this._pc.setLocalDescription(offer);

        // Esperar ICE gathering
        await this._waitForIceGathering();

        // Enviar offer al servidor, recibir answer
        const resp = await fetch(this._opts.offerUrl, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({
                sdp:     this._pc.localDescription.sdp,
                type:    this._pc.localDescription.type,
                peer_id: this._peerId,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Error en señalización WebRTC');
        }

        const answer = await resp.json();
        await this._pc.setRemoteDescription(
            new RTCSessionDescription({ sdp: answer.sdp, type: answer.type })
        );

        console.log('[VideoPlayer] SDP exchange completado');
    }

    _waitForIceGathering() {
        return new Promise((resolve) => {
            if (this._pc.iceGatheringState === 'complete') {
                resolve();
                return;
            }
            const check = setInterval(() => {
                if (!this._pc || this._pc.iceGatheringState === 'complete') {
                    clearInterval(check);
                    resolve();
                }
            }, 100);
            // Timeout de 5s para no quedarse esperando indefinidamente
            setTimeout(() => { clearInterval(check); resolve(); }, 5000);
        });
    }

    async _closePeer() {
        if (this._pc) {
            this._pc.ontrack               = null;
            this._pc.oniceconnectionstatechange = null;
            try { this._pc.close(); } catch (_) {}
            this._pc = null;
        }
        if (this._video.srcObject) {
            this._video.srcObject.getTracks().forEach(t => t.stop());
            this._video.srcObject = null;
        }
    }

    _scheduleReconnect(captureOptions) {
        this._clearReconnect();
        const delay = Math.min(3000 + this._reconnects * 2000, 15000); // backoff
        console.log(`[VideoPlayer] Reconectando en ${delay}ms (intento ${this._reconnects + 1})`);
        this._reconnectT = setTimeout(async () => {
            this._reconnects++;
            await this.connect(captureOptions);
        }, delay);
    }

    _clearReconnect() {
        if (this._reconnectT) {
            clearTimeout(this._reconnectT);
            this._reconnectT = null;
        }
    }

    _setState(state) {
        this._state = state;
        this._opts.onStateChange({ state, recording: this._recording });
    }
}
