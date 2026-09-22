import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html = fs.readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
const start = html.indexOf('        // One mode is applied');
const end = html.indexOf('        window.toggleVideoSettings', start);
const elements = new Map();
const get = id => {
    if (!elements.has(id)) elements.set(id, {value:'', textContent:'', disabled:false, classList:{toggle(){}, remove(){}}});
    return elements.get(id);
};
let calls = [], fail = false;
const context = {
    window:{}, document:{getElementById:get}, setInterval(){return 1;},
    fetch: async (url, options) => {
        if (options) {
            calls.push([url, JSON.parse(options.body)]);
            return {ok:!fail,json:async()=>fail ? {error:'Modelo inválido'} : {updated:true}};
        }
        return {ok:true,json:async()=>({mode:'off', active:false, inference_ms:0, governor:{mode:'off'}})};
    }
};
vm.createContext(context);
vm.runInContext(html.slice(start,end), context);
get('visionMode').value='segment';
get('visionDetectModel').value='yolo26n.pt';
get('visionSegmentModel').value='yolo26n-seg.pt';
get('visionDetectSize').value='640';
get('visionSegmentSize').value='416';
get('visionConfidence').value='.45';
get('visionClasses').value='person, cow';
get('visionThresholds').value='{"cow":0.4}';
await context.window.applyVision();
assert.equal(calls.length,1);
assert.equal(calls[0][0],'/api/vision/config');
assert.equal(calls[0][1].pipeline_mode,'segment');
assert.deepEqual(calls[0][1].enabled_classes,['person','cow']);
assert.equal(get('visionApply').disabled,false);
fail=true;
await context.window.applyVision();
assert.equal(get('visionMessage').textContent,'Modelo inválido');
get('visionThresholds').value='invalid JSON';
await context.window.applyVision();
assert.equal(calls.length,2);
assert.equal(get('visionApply').disabled,false);
assert.ok(!html.includes('Enable SEG'));
assert.ok(!html.includes('Enable DETECT'));
