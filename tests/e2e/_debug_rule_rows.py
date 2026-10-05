"""Debug-only: the horizontal rules of a fixture's source crop and of its
rebuild's, as the overlay test cuts them - each rule's y from its crop's
top and its thickness, in points, paired in order.

python3 tests/e2e/_debug_rule_rows.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz
import numpy as np

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf, _crop_rects

Z = 6.0


def rules(pdf, index, rect):
    page = fitz.open(pdf)[index]
    pix = page.get_pixmap(matrix=fitz.Matrix(Z, Z), clip=rect)
    px = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    dark = px.max(axis=2) < 110
    rows = np.flatnonzero(dark.mean(axis=1) > 0.25)
    out, start = [], None
    for i, r in enumerate(rows):
        if start is None:
            start = r
        if i + 1 == len(rows) or rows[i + 1] != r + 1:
            out.append(((start + r + 1) / 2 / Z, (r + 1 - start) / Z))
            start = None
    return out


fx = Path(sys.argv[1])
t = _extract_table(fx)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_single_table_pdf(t, td, "overlay_doc"))
    s, o = _crop_rects(fitz, fx, 0, pdf, t)
    a, b = rules(fx, 0, s), rules(pdf, 1, o)
    print(f"source crop h {s.height:.2f}  rebuild crop h {o.height:.2f}")
    for k in range(max(len(a), len(b))):
        sa = f"{a[k][0]:7.2f} ({a[k][1]:.2f})" if k < len(a) else " " * 14
        sb = f"{b[k][0]:7.2f} ({b[k][1]:.2f})" if k < len(b) else " " * 14
        d = f"{b[k][0] - a[k][0]:+.2f}" if k < len(a) and k < len(b) else ""
        print(f"  {sa}   {sb}   {d}")
