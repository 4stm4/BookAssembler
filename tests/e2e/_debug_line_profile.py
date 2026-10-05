"""Debug-only: the vertical ink profile of one printed line in the overlay
crops, source against rebuild - ink share per 0.25pt row - with each
profile's baseline (the last row at 30% of its densest) and top.

python3 tests/e2e/_debug_line_profile.py <pdf> <y0> <y1> [x_from x_to]   (crop points, width shares)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import (
    _build_single_table_pdf, _output_table_rect, _render_crop, _source_table_rect, _table_texts,
)

pdf, y0, y1 = Path(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
x_from = float(sys.argv[4]) if len(sys.argv) > 5 else 0.42
x_to = float(sys.argv[5]) if len(sys.argv) > 5 else 0.97
table = _extract_table(pdf)
STEP = 0.25


def profile(img, height_pt):
    grey = np.asarray(img.convert("L"), dtype=np.uint8)
    k = height_pt / grey.shape[0]
    w = grey.shape[1]
    ink = grey[int(y0 / k):int(y1 / k), int(x_from * w):int(x_to * w)] < 160
    rows = ink.mean(axis=1)
    per = max(1, int(round(STEP / k)))
    return [float(rows[i:i + per].mean()) for i in range(0, len(rows), per)]


with tempfile.TemporaryDirectory() as td:
    out = Path(_build_single_table_pdf(table, td, "lp"))
    src_rect = _source_table_rect(fitz, pdf, 0, table)
    s = profile(_render_crop(fitz, pdf, 0, src_rect, 8.0), src_rect.height)
    o = profile(_render_crop(fitz, out, 1, _output_table_rect(fitz, out, 1, _table_texts(table)), 8.0), src_rect.height)
for name, p in (("src", s), ("out", o)):
    peak = max(p)
    top = next(i for i, v in enumerate(p) if v > 0.02)
    base = max(i for i, v in enumerate(p) if v >= 0.3 * peak)
    print(f"{name}: top {y0 + top * STEP:.2f}  baseline {y0 + base * STEP:.2f}  ink {sum(p) * STEP:.2f}")
for i in range(max(len(s), len(o))):
    a = s[i] if i < len(s) else 0
    b = o[i] if i < len(o) else 0
    print(f"{y0 + i * STEP:6.2f} {'#' * int(a * 60):30s}|{'#' * int(b * 60)}")
