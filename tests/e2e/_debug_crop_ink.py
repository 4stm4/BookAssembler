"""Debug-only: the texts that bound the overlay crop on a fixture's source
page and its rebuild - each found text's box and the ink _ink_of puts it
at, the topmost and bottommost few.

python3 tests/e2e/_debug_crop_ink.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_toc_overlay import _ink_of
from tests.e2e.test_visual_overlay import _build_single_table_pdf, _table_lines

fx = Path(sys.argv[1])
t = _extract_table(fx)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_single_table_pdf(t, td, "overlay_doc"))
    src, out = fitz.open(fx)[0], fitz.open(pdf)[1]
    lines = [l for l in dict.fromkeys(_table_lines(t)) if src.search_for(l) and out.search_for(l)]
    for label, page in (("source", src), ("rebuild", out)):
        found = sorted(((r, _ink_of(fitz, page, r), l) for l in lines for r in page.search_for(l)),
                       key=lambda x: x[1].y0)
        print(label)
        for r, i, l in found[:3] + found[-4:]:
            print(f"   {l[:24]!r:28} box {r.y0:6.1f}-{r.y1:6.1f} x {r.x0:5.1f}-{r.x1:5.1f}   "
                  f"ink {i.y0:6.1f}-{i.y1:6.1f} x {i.x0:5.1f}-{i.x1:5.1f}")
