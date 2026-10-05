"""Debug-only: the vertical and horizontal rules inside the overlay crops,
source against rebuild - pixel columns (rows) inked over most of the crop's
height (width) - as centres in the source crop's points.

python3 tests/e2e/_debug_crop_rules.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf, _crop_rects, _render_crop

pdf = Path(sys.argv[1])
table = _extract_table(pdf)


def rules(img, w_pt, h_pt, axis, share):
    ink = np.asarray(img.convert("L"), dtype=np.uint8) < 160
    k = (w_pt if axis == 0 else h_pt) / ink.shape[1 - axis]
    hits = np.flatnonzero(ink.mean(axis=axis) > share)
    out, start, prev = [], None, None
    for i in list(hits) + [None]:
        if start is None:
            start = prev = i
        elif i is None or i - prev > 1:
            out.append(((start + prev + 1) / 2 * k, (prev + 1 - start) * k))
            start = prev = i
        else:
            prev = i
    return out


with tempfile.TemporaryDirectory() as td:
    out = Path(_build_single_table_pdf(table, td, "cr"))
    sr, orr = _crop_rects(fitz, pdf, 0, out, table)
    s_img, o_img = _render_crop(fitz, pdf, 0, sr, 6.0), _render_crop(fitz, out, 1, orr, 6.0)
for name, axis, share in (("verticals", 0, 0.5), ("horizontals", 1, 0.5)):
    s = rules(s_img, sr.width, sr.height, axis, share)
    o = rules(o_img, sr.width, sr.height, axis, share)
    print(name)
    print("  src", " ".join(f"{c:.1f}({w:.1f})" for c, w in s))
    print("  out", " ".join(f"{c:.1f}({w:.1f})" for c, w in o))
