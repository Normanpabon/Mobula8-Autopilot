"""Normalized selection shared by segmentation and detection."""
import json
import os
from pathlib import Path
from dataclasses import dataclass
import numpy as np

ROWS, COLS = 8, 12
CONFIG_FILE = Path(__file__).with_name('vision_roi.json')


@dataclass(frozen=True)
class RegionSelection:
    cells: tuple = (True,) * (ROWS * COLS)

    def __post_init__(self):
        if len(self.cells) != ROWS * COLS or any(type(v) is not bool for v in self.cells):
            raise ValueError(f'Se requieren {ROWS * COLS} celdas booleanas')

    @classmethod
    def load(cls, path=CONFIG_FILE):
        try:
            return cls(tuple(json.loads(path.read_text())['cells']))
        except FileNotFoundError:
            return cls()

    def save(self, path=CONFIG_FILE):
        temporary = path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(self.status, indent=2) + '\n')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @property
    def status(self):
        return {'rows': ROWS, 'cols': COLS, 'cells': list(self.cells),
                'selected_count': sum(self.cells), 'total_count': ROWS * COLS}

    def mask(self, height, width):
        # Same proportional boundaries as the CSS grid, including odd sizes.
        rows = np.minimum(np.arange(height) * ROWS // height, ROWS - 1)
        cols = np.minimum(np.arange(width) * COLS // width, COLS - 1)
        return np.asarray(self.cells, dtype=np.uint8).reshape(ROWS, COLS)[rows[:, None], cols[None, :]] * 255
