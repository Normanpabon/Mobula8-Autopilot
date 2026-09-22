export const ROWS = 8, COLS = 12;

export function cellAt(clientX, clientY, rect) {
    if (rect.width <= 0 || rect.height <= 0 || clientX < rect.left || clientY < rect.top ||
        clientX >= rect.left + rect.width || clientY >= rect.top + rect.height) return -1;
    return Math.floor((clientY - rect.top) / rect.height * ROWS) * COLS +
        Math.floor((clientX - rect.left) / rect.width * COLS);
}

export class VisionROI {
    constructor(video, surface) {
        this.video = video;
        this.surface = surface;
        this.grid = document.getElementById('visionRoiGrid');
        this.edit = document.getElementById('roiEdit');
        this.tools = document.getElementById('roiTools');
        this.message = document.getElementById('roiMessage');
        this.cells = Array(ROWS * COLS).fill(true);
        this.draft = [...this.cells];
        this.editing = false;
        this.loaded = false;
        this.busy = false;
        this.paint = null;
        this.buttons = this.cells.map((_, i) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'roi-cell';
            button.setAttribute('aria-label', `Fila ${Math.floor(i / COLS) + 1}, columna ${i % COLS + 1}`);
            button.addEventListener('click', event => {
                if (event.detail === 0 && this.editing && !this.busy) {
                    this.draft[i] = !this.draft[i];
                    this.render();
                }
            });
            this.grid.append(button);
            return button;
        });
        this.edit.addEventListener('click', () => this.open());
        document.getElementById('roiAll').addEventListener('click', () => this.fill(true));
        document.getElementById('roiNone').addEventListener('click', () => this.fill(false));
        document.getElementById('roiApply').addEventListener('click', () => this.apply());
        document.getElementById('roiCancel').addEventListener('click', () => this.cancel());
        this.grid.addEventListener('pointerdown', event => {
            if (!this.editing || this.busy || event.button !== 0) return;
            const index = cellAt(event.clientX, event.clientY, this.grid.getBoundingClientRect());
            if (index < 0) return;
            event.preventDefault();
            this.paint = !this.draft[index];
            this.grid.setPointerCapture(event.pointerId);
            this.draft[index] = this.paint;
            this.render();
        });
        this.grid.addEventListener('pointermove', event => {
            if (this.paint === null || this.busy) return;
            const index = cellAt(event.clientX, event.clientY, this.grid.getBoundingClientRect());
            if (index >= 0) { this.draft[index] = this.paint; this.render(); }
        });
        for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) {
            this.grid.addEventListener(name, () => { this.paint = null; });
        }
        new ResizeObserver(() => this.sync()).observe(video);
        video.addEventListener('resize', () => this.sync());
        this.render();
        this.load();
    }

    async request(body) {
        const response = await fetch('/api/vision/roi', body ? {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
        } : {cache: 'no-store'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'No se pudo cargar el área');
        if (data.rows !== ROWS || data.cols !== COLS || data.cells?.length !== ROWS * COLS) {
            throw new Error('Grilla incompatible');
        }
        return data;
    }

    async load() {
        this.loaded = false;
        try {
            const data = await this.request();
            this.cells = [...data.cells];
            this.draft = [...this.cells];
            this.loaded = true;
            this.render();
        } catch (error) { this.message.textContent = error.message; this.sync(); }
    }

    async open() {
        if (this.busy) return;
        // Re-read shared server state when opening the editor.
        await this.load();
        if (!this.loaded) return;
        for (const id of ['yoloPanel', 'rcPanel', 'videoSettingsPanel']) { document.getElementById(id)?.classList.remove('open'); }
        this.editing = true;
        this.draft = [...this.cells];
        this.render();
    }

    fill(selected) {
        if (this.busy) return;
        this.draft.fill(selected);
        this.render();
    }

    cancel() {
        if (this.busy) return;
        this.editing = false;
        this.paint = null;
        this.draft = [...this.cells];
        this.render();
    }

    async apply() {
        if (this.busy) return;
        this.busy = true;
        this.paint = null;
        this.render();
        try {
            const data = await this.request({cells: this.draft});
            this.cells = [...data.cells];
            this.editing = false;
        } catch (error) {
            this.message.textContent = error.message;
            this.busy = false;
            this.setDisabled();
            return;
        }
        this.busy = false;
        this.render();
    }

    setDisabled() {
        this.edit.disabled = this.busy;
        for (const id of ['roiAll', 'roiNone', 'roiApply', 'roiCancel']) {
            document.getElementById(id).disabled = this.busy;
        }
    }

    render() {
        const cells = this.editing ? this.draft : this.cells;
        this.grid.classList.toggle('editing', this.editing);
        this.tools.hidden = !this.editing;
        this.edit.textContent = this.editing ? '▦ Editando área · clic o arrastre' : '▦ Área IA';
        this.edit.setAttribute('aria-expanded', String(this.editing));
        this.buttons.forEach((button, i) => {
            button.classList.toggle('excluded', !cells[i]);
            button.setAttribute('aria-pressed', String(cells[i]));
            button.tabIndex = this.editing ? 0 : -1;
        });
        const selected = cells.filter(Boolean).length;
        this.message.textContent = this.busy ? 'Guardando área…' :
            `${selected}/96 celdas ${this.editing ? 'en edición · pulsa Aplicar' : 'activas'}${!selected ? (this.editing ? ' · pausará la inferencia' : ' · inferencia pausada') : ''}`;
        this.setDisabled();
        this.sync();
    }

    sync() {
        const video = this.video.getBoundingClientRect();
        const surface = this.surface.getBoundingClientRect();
        Object.assign(this.grid.style, {
            left: `${video.left - surface.left}px`, top: `${video.top - surface.top}px`,
            width: `${video.width}px`, height: `${video.height}px`,
        });
        this.grid.hidden = !this.loaded || !video.width || this.video.style.display === 'none';
    }
}
