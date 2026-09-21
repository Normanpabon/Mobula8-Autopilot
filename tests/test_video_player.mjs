import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../frontend/js/modules/VideoPlayer.js', import.meta.url), 'utf8');
const { VideoPlayer } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('NTSC request and negotiated capture reach UI callback', async () => {
    let request, state;
    const player = new VideoPlayer({}, { onStateChange: value => { state = value; } });
    player._createPeerConnection = async () => player._setState('connected');
    const original = globalThis.fetch;
    globalThis.fetch = async (_, options) => {
        request = JSON.parse(options.body);
        return { ok: true, json: async () => ({ width:640, height:480, fps:30 }) };
    };
    try {
        await player.connect();
        assert.equal(request.width, 720);
        assert.equal(request.height, 480);
        assert.equal(request.fps, 30000 / 1001);
        assert.equal(state.capture.width, 640);
    } finally { globalThis.fetch = original; }
});

test('encoder error does not activate recording', async () => {
    const player = new VideoPlayer({});
    const original = globalThis.fetch;
    globalThis.fetch = async () => ({ ok:false, json:async () => ({error:'Encoder failed'}) });
    try {
        await assert.rejects(player.startRecording(), /Encoder failed/);
        assert.equal(player.recording, false);
    } finally { globalThis.fetch = original; }
});

test('server-side recording failure clears UI recording state', async () => {
    let state;
    const player = new VideoPlayer({}, {onStateChange:value => { state=value; }});
    player._recording = true;
    const original = globalThis.fetch;
    globalThis.fetch = async () => ({ ok:true, json:async () => ({
        capture:{width:720,height:480,fps:30000/1001},
        recorder:{recording:false,error:'No frames'},
    }) });
    try {
        await player.getServerStatus();
        assert.equal(player.recording, false);
        assert.equal(state.recorder.error, 'No frames');
    } finally { globalThis.fetch = original; }
});
