"""Debug-only: a word's box as search_for gives it, against its ink, on a
fixture's source page and on its rebuild - where the overlay crop is cut
from text, the box's top and bottom are the crop's.

python3 tests/e2e/_debug_word_box_ink.py <pdf> <word> [...]
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz
import numpy as np

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf

Z = 6.0


def show(label, page, word):
    for r in page.search_for(word):
        pix = page.get_pixmap(matrix=fitz.Matrix(Z, Z), clip=fitz.Rect(r.x0, r.y0 - 6, r.x1, r.y1 + 6))
        px = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
        dark = px.max(axis=2) < 110
        # A rule crosses the whole word; a glyph row does not.
        rows = np.flatnonzero(dark.any(axis=1) & (dark.mean(axis=1) < 0.6))
        top, bottom = (r.y0 - 6 + rows[0] / Z, r.y0 - 6 + (rows[-1] + 1) / Z) if len(rows) else (None, None)
        print(f"  {label} {word!r}: box {r.y0:7.2f}-{r.y1:7.2f}  ink {top:7.2f}-{bottom:7.2f}  "
              f"box over ink {top - r.y0:+.2f} / under {r.y1 - bottom:+.2f}")


fx = Path(sys.argv[1])
t = _extract_table(fx)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_single_table_pdf(t, td, "overlay_doc"))
    src, out = fitz.open(fx)[0], fitz.open(pdf)[1]
    for w in sys.argv[2:]:
        show("source ", src, w)
        show("rebuild", out, w)
