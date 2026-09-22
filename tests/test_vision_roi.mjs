import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../frontend/js/modules/VisionROI.js',import.meta.url),'utf8');
const {cellAt, VisionROI} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('cell selection follows video bounds, not letterboxing, across 4:3 and 16:9', () => {
    for (const rect of [{left:100,top:50,width:640,height:480},{left:0,top:100,width:1920,height:1080}]) {
        assert.equal(cellAt(rect.left-1,rect.top,rect),-1);
        assert.equal(cellAt(rect.left,rect.top,rect),0);
        assert.equal(cellAt(rect.left+rect.width-.1,rect.top+rect.height-.1,rect),95);
        assert.equal(cellAt(rect.left+rect.width,rect.top,rect),-1);
        assert.equal(cellAt(rect.left+rect.width*.51,rect.top+rect.height*.51,rect),54);
    }
});

test('draft edits require Apply, Cancel restores, and failed saves keep draft', async () => {
    const elements = new Map();
    function element() {
        return {style:{}, classList:{toggle(){},remove(){}}, hidden:false, listeners:{},
            addEventListener(name,fn){this.listeners[name]=fn;}, setAttribute(){}, append(){},
            getBoundingClientRect(){return {left:0,top:0,width:120,height:80};}, setPointerCapture(){}};
    }
    for(const id of ['visionRoiGrid','roiEdit','roiTools','roiMessage','roiAll','roiNone','roiApply','roiCancel']) elements.set(id,element());
    const saved = {fetch:globalThis.fetch, document:globalThis.document, ResizeObserver:globalThis.ResizeObserver};
    let stored=Array(96).fill(true), fail=false, writes=0;
    globalThis.document={getElementById:id=>elements.get(id),createElement:element};
    globalThis.ResizeObserver=class {observe(){}};
    globalThis.fetch=async (_,options)=>{
        if(options?.method==='POST') {
            writes++;
            if(!fail) stored=JSON.parse(options.body).cells;
        }
        return {ok:!fail,json:async()=>fail ? {error:'Disco lleno'} : {rows:8,cols:12,cells:stored}};
    };
    try {
        const ui=new VisionROI(element(),element());
        await new Promise(resolve=>setImmediate(resolve));
        await ui.open();
        ui.fill(false);
        assert.equal(writes,0);
        ui.cancel();
        assert.equal(ui.cells.filter(Boolean).length,96);
        await ui.open();
        const grid=elements.get('visionRoiGrid');
        grid.listeners.pointerdown({button:0,clientX:5,clientY:5,pointerId:1,preventDefault(){}});
        grid.listeners.pointermove({clientX:15,clientY:5});
        grid.listeners.pointerup();
        assert.deepEqual(ui.draft.slice(0,3),[false,false,true]);
        await ui.apply();
        assert.equal(stored.filter(Boolean).length,94);
        assert.equal(ui.editing,false);
        await ui.open();
        ui.fill(false);
        fail=true;
        await ui.apply();
        assert.equal(ui.cells.filter(Boolean).length,94);
        assert.equal(ui.editing,true);
        assert.equal(elements.get('roiMessage').textContent,'Disco lleno');
        fail=false;
        await ui.apply();
        assert.equal(stored.filter(Boolean).length,0);
        assert.match(elements.get('roiMessage').textContent,/inferencia pausada/);
    } finally {Object.assign(globalThis,saved);}
});
