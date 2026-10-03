"""Debug-only: how test_visual_overlay finds the rebuilt table - each of
the table's texts of six characters or more, whether search_for finds it
on the rebuilt page and where; the anchor they make; the crop.

python3 tests/e2e/_debug_output_anchor.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf, _output_table_rect, _table_texts

table = _extract_table(Path(sys.argv[1]))
texts = _table_texts(table)
with tempfile.TemporaryDirectory() as td:
    out = Path(_build_single_table_pdf(table, td, "anchor"))
    page = fitz.open(out)[1]
    for t in texts:
        if len(t) >= 6:
            hits = page.search_for(t)
            print(f"{'  ' if hits else 'NO'} {min((h.y0 for h in hits), default=0):6.1f}-{max((h.y1 for h in hits), default=0):6.1f}  {t[:50]!r}")
    print("crop", _output_table_rect(fitz, out, 1, texts))
    if len(sys.argv) > 2:
        text = page.get_text()
        i = text.find(sys.argv[2])
        print(repr(text[i:i + 400]))
        cell = next(t for t in texts if t.startswith(sys.argv[2]))
        print(repr(cell[:400]))
