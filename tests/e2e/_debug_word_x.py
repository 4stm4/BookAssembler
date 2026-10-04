"""Debug-only: where given words stand across the overlay crops, source
against rebuild, in points from each crop's left edge.

python3 tests/e2e/_debug_word_x.py <pdf> <word>...
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf, _output_table_rect, _source_table_rect, _table_texts

pdf = Path(sys.argv[1])
table = _extract_table(pdf)
src_rect = _source_table_rect(fitz, pdf, 0, table)
src = [w for w in fitz.open(pdf)[0].get_text("words") if src_rect.contains(fitz.Rect(w[:4]))]
with tempfile.TemporaryDirectory() as td:
    out_pdf = Path(_build_single_table_pdf(table, td, "wx"))
    out_rect = _output_table_rect(fitz, out_pdf, 1, _table_texts(table))
    out = [w for w in fitz.open(out_pdf)[1].get_text("words") if out_rect.contains(fitz.Rect(w[:4]))]
for word in sys.argv[2:]:
    s = [(w[0] - src_rect.x0, w[2] - src_rect.x0, w[1] - src_rect.y0) for w in src if w[4] == word][:3]
    o = [(w[0] - out_rect.x0, w[2] - out_rect.x0, w[1] - out_rect.y0) for w in out if w[4] == word][:3]
    print(word, "src", [f"{a:.1f}-{b:.1f}@{y:.0f}" for a, b, y in s], "out", [f"{a:.1f}-{b:.1f}@{y:.0f}" for a, b, y in o])
