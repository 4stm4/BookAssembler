"""Debug-only: where each word of a contents fixture's page inks on the
source page and on the product's rebuild of it (_ink_of on both), and the
difference.

python3 tests/e2e/_debug_toc_word_edges.py <pdf> <page>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz

from tests.e2e.test_toc_overlay import _build_toc_pdf, _extract_tocs
from tests.e2e.test_visual_overlay import _ink_of

fx, pg = Path(sys.argv[1]), int(sys.argv[2])
tocs = _extract_tocs(fx)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_toc_pdf(tocs, td, "toc"))
    src, out = fitz.open(fx)[pg], fitz.open(pdf)[pg]
    for w in src.get_text("words"):
        hits = out.search_for(w[4])
        if not hits:
            print(f"  {w[4]!r:22} not in rebuild")
            continue
        a = _ink_of(fitz, src, fitz.Rect(w[:4]))
        b = min((_ink_of(fitz, out, h) for h in hits), key=lambda r: abs(r.y0 - a.y0) + abs(r.x0 - a.x0))
        print(f"  {w[4]!r:22} src x {a.x0:6.1f}-{a.x1:6.1f} y {a.y0:6.1f}-{a.y1:6.1f}   "
              f"out x {b.x0:6.1f}-{b.x1:6.1f} y {b.y0:6.1f}-{b.y1:6.1f}   dx0 {b.x0 - a.x0:+.1f} dx1 {b.x1 - a.x1:+.1f}")
