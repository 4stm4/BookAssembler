"""Debug-only: where a table fixture's overlay misses lie - the pixels the
test's masks disagree on, counted over a grid of zones of the crop (rows
of zones top to bottom, columns left to right), as shares of its area.

python3 tests/e2e/_debug_miss_zones.py <pdf> [rows] [cols]
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import (
    _build_single_table_pdf, _crop_rects, _ink_mask, _render_crop,
)

fx = Path(sys.argv[1])
nr = int(sys.argv[2]) if len(sys.argv) > 2 else 6
nc = int(sys.argv[3]) if len(sys.argv) > 3 else 4
t = _extract_table(fx)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_single_table_pdf(t, td, "overlay_doc"))
    s, o = _crop_rects(fitz, fx, 0, pdf, t)
    ma, mb = _ink_mask(_render_crop(fitz, fx, 0, s)), _ink_mask(_render_crop(fitz, pdf, 1, o))
    miss = ma ^ mb
    ink = float(ma.size)
    h, w = miss.shape
    print(f"total {miss.sum() / ink:.1%}  (rows of {h // nr}px, cols of {w // nc}px)")
    for r in range(nr):
        cells = [miss[r * h // nr:(r + 1) * h // nr, c * w // nc:(c + 1) * w // nc].sum() / ink for c in range(nc)]
        print("  " + "  ".join(f"{v:5.1%}" for v in cells))
