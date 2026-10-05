"""Debug-only: the median stroke width (pdf_adapter._measure_stroke_pt) of
the words of four letters or more inside the overlay crops, source
against rebuild.

python3 tests/e2e/_debug_word_strokes.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from src.adapters.pdf_adapter import _measure_stroke_pt
from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf, _crop_rects

pdf = Path(sys.argv[1])
table = _extract_table(pdf)


def median_stroke(page, rect):
    vals = sorted(v for w in page.get_text("words") if rect.contains(fitz.Rect(w[:4]))
                  and sum(ch.isalpha() for ch in w[4]) >= 4
                  for v in [_measure_stroke_pt(page, fitz.Rect(w[:4]))] if v)
    return vals[len(vals) // 2] if vals else None, len(vals)


with tempfile.TemporaryDirectory() as td:
    out = Path(_build_single_table_pdf(table, td, "ws"))
    sr, orr = _crop_rects(fitz, pdf, 0, out, table)
    print("source", median_stroke(fitz.open(pdf)[0], sr))
    print("rebuild", median_stroke(fitz.open(out)[1], orr))
