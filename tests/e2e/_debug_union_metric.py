"""Debug-only: both overlay tests' crops on every fixture, measured two
ways - disagreeing pixels over the whole crop, and over the ink of either.

python3 tests/e2e/_debug_union_metric.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz

from tests.e2e.test_assembled_table_pdf import (
    FIXTURE_A, FIXTURE_B, FIXTURE_C, FIXTURE_D, FIXTURE_E, _extract_table,
)
from tests.e2e.test_toc_overlay import (
    TOC_A, TOC_B, TOC_C, _build_toc_pdf, _crop_rects as _toc_crops, _extract_tocs, _page_texts,
)
from tests.e2e.test_visual_overlay import (
    _build_single_table_pdf, _crop_rects, _ink_mask, _render_crop,
)


import numpy as np


def union(ma, mb, reach=0):
    """Ink of either that the other has none of within reach pixels, over
    the ink of either."""
    def near(m):
        out = m.copy()
        for dy in range(-reach, reach + 1):
            for dx in range(-reach, reach + 1):
                out |= np.roll(np.roll(m, dy, 0), dx, 1)
        return out
    miss = (ma & ~near(mb)) | (mb & ~near(ma))
    return float(miss.sum()) / float((ma | mb).sum())


def report(name, a, b):
    ma, mb = _ink_mask(a), _ink_mask(b)
    xor = float((ma ^ mb).sum())
    shift1 = np.roll(ma, 1, 1)
    shift2 = np.roll(ma, 2, 1)
    print(f"{name:28} area {xor / ma.size:6.1%}   union {union(ma, mb):6.1%}"
          f"  r1 {union(ma, mb, 1):6.1%}  r2 {union(ma, mb, 2):6.1%}"
          f"   | self+1px {union(ma, shift1):6.1%}  self+2px {union(ma, shift2):6.1%}")


with tempfile.TemporaryDirectory() as td:
    for fx in (FIXTURE_A, FIXTURE_B, FIXTURE_C, FIXTURE_D, FIXTURE_E):
        t = _extract_table(fx)
        pdf = Path(_build_single_table_pdf(t, td, fx.stem))
        s, o = _crop_rects(fitz, fx, 0, pdf, t)
        report(fx.stem, _render_crop(fitz, fx, 0, s), _render_crop(fitz, pdf, 1, o))
    for fx, page in ((TOC_A, 0), (TOC_B, 0), (TOC_C, 0), (TOC_C, 1), (TOC_C, 2)):
        tocs = _extract_tocs(fx)
        texts = _page_texts(tocs, page) if tocs else []
        if not texts:
            print(f"{fx.stem}_p{page:<22} no contents extracted")
            continue
        pdf = Path(_build_toc_pdf(tocs, td, fx.stem))
        out_page, s, o = _toc_crops(fitz, fx, page, pdf, texts)
        report(f"{fx.stem}_p{page}", _render_crop(fitz, fx, page, s), _render_crop(fitz, pdf, out_page, o))
