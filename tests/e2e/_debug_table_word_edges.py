"""Debug-only: where each word of a table fixture inks on the source page
and in the product's rebuild of the table (_ink_of on both), and the
difference - each pair offset by the first word's, as the overlay crops
align them.

python3 tests/e2e/_debug_table_word_edges.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf, _crop_rects, _ink_of

fx = Path(sys.argv[1])
t = _extract_table(fx)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_single_table_pdf(t, td, "overlay_doc"))
    s, o = _crop_rects(fitz, fx, 0, pdf, t)
    src, out = fitz.open(fx)[0], fitz.open(pdf)[1]
    for w in src.get_text("words"):
        r = fitz.Rect(w[:4])
        if not r.intersects(s):
            continue
        hits = out.search_for(w[4])
        if not hits:
            print(f"  {w[4]!r:22} not in rebuild")
            continue
        a = _ink_of(fitz, src, r)
        ax, ay = a.x0 - s.x0, a.y0 - s.y0
        best = min((_ink_of(fitz, out, h) for h in hits),
                   key=lambda b: abs(b.y0 - o.y0 - ay) + abs(b.x0 - o.x0 - ax))
        print(f"  {w[4]!r:22} src x {ax:6.1f}-{a.x1 - s.x0:6.1f} y {ay:6.1f}-{a.y1 - s.y0:6.1f}   "
              f"dx0 {best.x0 - o.x0 - ax:+.1f} dx1 {best.x1 - o.x0 - (a.x1 - s.x0):+.1f} "
              f"dy0 {best.y0 - o.y0 - ay:+.1f} dy1 {best.y1 - o.y0 - (a.y1 - s.y0):+.1f}")
