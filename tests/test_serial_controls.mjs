import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../frontend/js/modules/SerialControls.js', import.meta.url), 'utf8');
test('serial selector connects, exposes retry state and allows cancelling retries', async () => {
    const elements = new Map();
    for (const id of ['serialPort', 'serialBaud', 'serialStatus', 'serialError', 'serialConnect', 'serialDisconnect', 'serialRefresh']) {
        elements.set(id, {value: id === 'serialBaud' ? '115200' : '', options: [], listeners: {},
            addEventListener(name, cb) { this.listeners[name] = cb; },
            replaceChildren(option) { this.options = [option]; this.value = option.value; },
            add(option) { this.options.push(option); }, reportValidity() { return true; }});
    }
    let state = {connected: false, serial_port: null, serial_state: 'DISCONNECTED'};
    let tick;
    const calls = [];
    const context = {
        document: {getElementById: id => elements.get(id)},
        Option: function(text, value) { Object.assign(this, {text, value}); },
        window: {dispatchEvent() {}}, CustomEvent: function() {},
        setInterval(cb) { tick = cb; },
        async fetch(url, options) {
            calls.push([url, options]);
            let data = state;
            if (url.endsWith('/ports')) data = {platform: 'Windows', ports: [{device: 'COM12', description: 'Radio'}]};
            if (url.endsWith('/connect')) {
                state = {connected: false, serial_port: 'COM12', serial_state: 'RETRY_WAIT', serial_error: 'busy'};
                data = {retrying: true};
            }
            if (url.endsWith('/disconnect')) data = state = {connected: false, serial_port: null, serial_state: 'DISCONNECTED'};
            return {ok: true, async json() { return data; }};
        },
    };
    vm.runInNewContext(source, context);
    const flush = () => new Promise(resolve => setImmediate(resolve));
    await flush();
    const port = elements.get('serialPort');
    assert.equal(port.options[1].value, 'COM12');
    port.value = 'COM12';
    port.listeners.change();
    assert.equal(elements.get('serialConnect').disabled, false);
    await elements.get('serialConnect').listeners.click();
    assert.equal(JSON.parse(calls.find(([url]) => url.endsWith('/connect'))[1].body).port, 'COM12');
    assert.match(elements.get('serialStatus').textContent, /Windows.*RETRY_WAIT/);
    assert.equal(elements.get('serialDisconnect').disabled, false);
    await elements.get('serialDisconnect').listeners.click();
    assert.equal(elements.get('serialDisconnect').disabled, true);
    tick();
    await flush();
});
