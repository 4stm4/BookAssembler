"""Debug-only: the ink row bands of the source and rebuilt table crops (as
test_visual_overlay cuts them), both in the source crop's points - where
each printed line of ink starts and ends, side by side.

python3 tests/e2e/_debug_ink_rows.py <pdf> [max_bands] [x_from x_to, shares of the width]
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import (
    _build_single_table_pdf, _crop_rects, _render_crop,
)

ZOOM = 4.0


X_FROM = float(sys.argv[3]) if len(sys.argv) > 4 else 0.08
X_TO = float(sys.argv[4]) if len(sys.argv) > 4 else 0.92


def bands(img, height_pt):
    grey = np.asarray(img.convert("L"), dtype=np.uint8)
    w = grey.shape[1]
    grey = grey[:, int(X_FROM * w):int(X_TO * w)]     # inside the frame's verticals
    ink = (grey < 160).mean(axis=1)
    rows = ink > 0.002
    out, start = [], None
    for y, v in enumerate(list(rows) + [False]):
        if v and start is None:
            start = y
        elif not v and start is not None:
            k = height_pt / grey.shape[0]
            band = (grey[start:y] < 160).any(axis=0)
            xs = np.flatnonzero(band)
            kx = height_pt / grey.shape[0]       # crops scaled to the source's points both ways
            out.append((start * k, y * k, float(ink[start:y].max()), xs[0] * kx, xs[-1] * kx))
            start = None
    return out


pdf = Path(sys.argv[1])
n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
table = _extract_table(pdf)
with tempfile.TemporaryDirectory() as td:
    out = Path(_build_single_table_pdf(table, td, "ink"))
    src_rect, out_rect = _crop_rects(fitz, pdf, 0, out, table)
    s = bands(_render_crop(fitz, pdf, 0, src_rect, ZOOM), src_rect.height)
    o = bands(_render_crop(fitz, out, 1, out_rect, ZOOM), src_rect.height)
for i in range(min(n, max(len(s), len(o)))):
    a = s[i] if i < len(s) else None
    b = o[i] if i < len(o) else None
    fa = f"{a[0]:6.1f}-{a[1]:6.1f} x {a[3]:5.1f}-{a[4]:5.1f}" if a else " " * 30
    fb = f"{b[0]:6.1f}-{b[1]:6.1f} x {b[3]:5.1f}-{b[4]:5.1f}" if b else ""
    print(f"{i:3d}  src {fa}   out {fb}")
