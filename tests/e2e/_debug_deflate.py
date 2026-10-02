"""Debug-only: which cells of a fixture's table rules._deflate_boxes brings
down, and by how much (pt).

python3 tests/e2e/_debug_deflate.py <pdf>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

import src.analyzers.table.analyzer as analyzer
from src.analyzers.table.rules import _cell_text_of
from tests.e2e.test_assembled_table_pdf import _extract_table

real = analyzer._deflate_boxes


def traced(np, pymupdf, page, table):
    before = {id(c): c.visual_layout.bounding_box.y0 for r in table.grid for c in r
              if c.visual_layout and c.visual_layout.bounding_box}
    n = real(np, pymupdf, page, table)
    for r, row in enumerate(table.grid):
        for c in row:
            if id(c) in before and c.visual_layout.bounding_box.y0 != before[id(c)]:
                b = c.visual_layout.bounding_box
                print(f"{r:3d}  -{(b.y0 - before[id(c)]) * page.rect.height:5.2f}pt  "
                      f"box now {(b.y1 - b.y0) * page.rect.height:5.2f}pt  {_cell_text_of(c)[:40]!r}")
    print("deflated", n)
    return n


analyzer._deflate_boxes = traced
_extract_table(Path(sys.argv[1]))
