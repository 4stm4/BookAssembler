"""Debug-only: glyph stroke width of each table cell in the source against
the same text in the rebuilt PDF (pdf_adapter._measure_stroke_pt), with the
weight the rebuild set it in.

python3 tests/e2e/_debug_stroke_compare.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from src.adapters.pdf_adapter import _measure_stroke_pt
from src.analyzers.table.rules import _cell_text_of
from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf

pdf = Path(sys.argv[1])
table = _extract_table(pdf)
src = fitz.open(pdf)[0]
with tempfile.TemporaryDirectory() as td:
    out = fitz.open(_build_single_table_pdf(table, td, "stroke"))[1]
    for row in table.grid:
        for cell in row:
            text = _cell_text_of(cell)
            b = cell.visual_layout.bounding_box if cell.visual_layout else None
            if b is None or len(text) < 4 or "\n" in text:
                continue
            hits = out.search_for(text)
            if not hits:
                continue
            s = _measure_stroke_pt(src, fitz.Rect(b.x0 * src.rect.width, b.y0 * src.rect.height,
                                                  b.x1 * src.rect.width, b.y1 * src.rect.height))
            r = _measure_stroke_pt(out, hits[0])
            bold = cell.visual_layout.style.is_bold if cell.visual_layout.style else None
            print(f"src {s or 0:4.2f}  out {r or 0:4.2f}  bold {bold!s:5}  {text[:36]!r}")
