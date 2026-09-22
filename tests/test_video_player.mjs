import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../frontend/js/modules/VideoPlayer.js', import.meta.url), 'utf8');
const { VideoPlayer } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('digital request lets backend negotiate instead of forcing NTSC', async () => {
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
        assert.equal(request.profile, 'digital');
        assert.equal(request.width, undefined);
        assert.equal(request.height, undefined);
        assert.equal(request.fps, undefined);
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

test('analog PAL preset and explicit overrides survive client serialization', async () => {
    let request;
    const player = new VideoPlayer({});
    player._createPeerConnection = async () => {};
    const original = globalThis.fetch;
    globalThis.fetch = async (_, options) => {
        request = JSON.parse(options.body);
        return {ok:true, json:async () => ({})};
    };
    try {
        await player.connect({device_id: 2, profile:'analog', standard:'pal'});
        assert.deepEqual(request, {device_id:2, profile:'analog', standard:'pal'});
        await player.connect({profile:'digital', width:1280, height:720, fps:60});
        assert.equal(request.width, 1280);
        assert.equal(request.fps, 60);
    } finally { globalThis.fetch = original; }
});
const presetsSource = await readFile(new URL('../frontend/js/modules/VideoPresets.js', import.meta.url), 'utf8');
const presets = await import(`data:text/javascript;base64,${Buffer.from(presetsSource).toString('base64')}`);
test('switching camera preserves preset intent and correct display aspect', () => {
    assert.deepEqual(presets.captureOptions('3', 'digital'), {device_id:3, profile:'digital', standard:'ntsc'});
    assert.equal(presets.defaultAspect('digital'), 'native');
    assert.equal(presets.defaultAspect('analog'), '4:3');
});
