"""Debug-only: where a table fixture's overlay misses lie - the misses of
the test's mask, counted over a grid of zones of the crop (rows of zones
top to bottom, columns left to right), as shares of all the ink.

python3 tests/e2e/_debug_miss_zones.py <pdf> [rows] [cols]
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import (
    _MATCH_REACH_PX, _build_single_table_pdf, _crop_rects, _ink_mask, _near, _render_crop,
)

fx = Path(sys.argv[1])
nr = int(sys.argv[2]) if len(sys.argv) > 2 else 6
nc = int(sys.argv[3]) if len(sys.argv) > 3 else 4
t = _extract_table(fx)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_single_table_pdf(t, td, "overlay_doc"))
    s, o = _crop_rects(fitz, fx, 0, pdf, t)
    ma, mb = _ink_mask(_render_crop(fitz, fx, 0, s)), _ink_mask(_render_crop(fitz, pdf, 1, o))
    miss = (ma & ~_near(mb, _MATCH_REACH_PX)) | (mb & ~_near(ma, _MATCH_REACH_PX))
    ink = float((ma | mb).sum())
    h, w = miss.shape
    print(f"total {miss.sum() / ink:.1%}  (rows of {h // nr}px, cols of {w // nc}px)")
    for r in range(nr):
        cells = [miss[r * h // nr:(r + 1) * h // nr, c * w // nc:(c + 1) * w // nc].sum() / ink for c in range(nc)]
        print("  " + "  ".join(f"{v:5.1%}" for v in cells))
