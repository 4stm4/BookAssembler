"""Debug-only: how test_toc_overlay cuts one source page's contents - the
texts it bounds them by, in order, where each is found (as ink) on the
source page and on the rebuilt one, and the two rects.

python3 tests/e2e/_debug_toc_crop.py <pdf> <page>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz

from tests.e2e.test_toc_overlay import _build_toc_pdf, _crop_rects, _extract_tocs, _page_texts
from tests.e2e.test_toc_overlay import _ink_of

fx, page = Path(sys.argv[1]), int(sys.argv[2])
tocs = _extract_tocs(fx)
texts = _page_texts(tocs, page)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_toc_pdf(tocs, td, "toc"))
    out_page, s, o = _crop_rects(fitz, fx, page, pdf, texts)
    print("source", s, "rebuilt page", out_page, o)
    sp, op = fitz.open(fx)[page], fitz.open(pdf)[out_page]
    for t in texts:
        a = [round(_ink_of(fitz, sp, r).y0, 1) for r in sp.search_for(t)]
        b = [round(_ink_of(fitz, op, r).y0, 1) for r in op.search_for(t)]
        print(f"  {t[:40]!r:44} src {a[:4]}  out {b[:4]}")
