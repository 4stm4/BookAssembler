"""Debug-only: for each cell of a fixture's table, how far its box stands
above and below the ink inside it (pt), off the page's pixels.

python3 tests/e2e/_debug_box_pads.py <pdf>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

from src.analyzers.table.rules import _cell_text_of
from tests.e2e.test_assembled_table_pdf import _extract_table

ZOOM = 3.0
pdf = Path(sys.argv[1])
table = _extract_table(pdf)
page = pymupdf.open(pdf)[0]
pw, ph = page.rect.width, page.rect.height
for r, row in enumerate(table.grid):
    for cell in row:
        b = cell.visual_layout.bounding_box if cell.visual_layout else None
        if b is None:
            continue
        clip = pymupdf.Rect(b.x0 * pw, b.y0 * ph, b.x1 * pw, b.y1 * ph) & page.rect
        if clip.is_empty:
            continue
        pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), clip=clip, colorspace=pymupdf.csGRAY)
        ink = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width) < 160
        rows = np.flatnonzero(ink.mean(axis=1) > 0.01)
        if not len(rows):
            print(f"{r:3d}  no ink  {_cell_text_of(cell)[:30]!r}")
            continue
        top, bot = rows[0] / ZOOM, (rows[-1] + 1) / ZOOM
        print(f"{r:3d}  box {clip.height:5.1f}  ink {bot - top:5.1f}  above {top:5.1f}  below {clip.height - bot:5.1f}  "
              f"size {cell.visual_layout.style.font_size_pt if cell.visual_layout.style else 0:5.2f}  {_cell_text_of(cell)[:30]!r}")
