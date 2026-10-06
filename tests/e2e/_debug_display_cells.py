"""Debug-only: what _size_display_type sees on a table fixture - each
cell's text-layer size against the table's usual, and its box before and
after.

python3 tests/e2e/_debug_display_cells.py <pdf> [rows]
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import src.analyzers.table.analyzer as A
from src.analyzers.table import rules as R
from tests.e2e.test_assembled_table_pdf import _extract_table

ROWS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
real = A._size_display_type


def spy(np_, fitz_, page, table):
    sizes = sorted(c.visual_layout.style.font_size_pt for r in table.grid for c in r
                   if c.visual_layout is not None and c.visual_layout.style is not None)
    print("usual", sizes[len(sizes) // 2] if sizes else None)
    before = [[(R._cell_text_of(c)[:16], c.visual_layout.style.font_size_pt if c.visual_layout.style else None,
                round(c.visual_layout.bounding_box.x0 * 595, 1)) for c in r] for r in table.grid[:ROWS]]
    n = real(np_, fitz_, page, table)
    after = [[round(c.visual_layout.bounding_box.x0 * 595, 1) for c in r] for r in table.grid[:ROWS]]
    for b, a in zip(before, after):
        print(b, "->", a)
    print("resized", n)
    return n


A._size_display_type = spy
_extract_table(Path(sys.argv[1]))
