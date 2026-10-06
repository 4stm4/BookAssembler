"""Debug-only: the leader dots of one row of a table fixture, on the source
page and in the rebuild - their x from each crop's left edge - to compare
the dots' pitch and phase.

python3 tests/e2e/_debug_leader_dots.py <pdf> <word on the row>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz
import numpy as np

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_toc_overlay import _ink_of
from tests.e2e.test_visual_overlay import _build_single_table_pdf, _crop_rects


def dots(page, crop, word):
    hit = _ink_of(fitz, page, page.search_for(word)[0])
    band = fitz.Rect(hit.x1 + 2, hit.y0, crop.x1, hit.y1)
    pix = page.get_pixmap(matrix=fitz.Matrix(6, 6), clip=band)
    g = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].mean(axis=2)
    cols = (g < 160).any(axis=0)
    xs, start = [], None
    for i, c in enumerate(list(cols) + [False]):
        if c and start is None:
            start = i
        elif not c and start is not None:
            xs.append(round(band.x0 - crop.x0 + (start + i) / 12, 1))
            start = None
    return xs


fx = Path(sys.argv[1])
t = _extract_table(fx)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_single_table_pdf(t, td, "overlay_doc"))
    s, o = _crop_rects(fitz, fx, 0, pdf, t)
    print("source ", dots(fitz.open(fx)[0], s, sys.argv[2])[:14])
    print("rebuild", dots(fitz.open(pdf)[1], o, sys.argv[2])[:14])
