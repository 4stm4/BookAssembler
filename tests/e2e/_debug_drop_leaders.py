"""Debug-only: the rows of a fixture's table as _drop_leaders gets them and
leaves them, for rows whose text contains a given string.

python3 tests/e2e/_debug_drop_leaders.py <pdf> <substring>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

import src.analyzers.table.analyzer as analyzer
from src.analyzers.table.rules import _cell_text_of
from tests.e2e.test_assembled_table_pdf import _extract_table

pdf, needle = Path(sys.argv[1]), sys.argv[2]
real = analyzer._drop_leaders


def show(table, when):
    for r, row in enumerate(table.grid):
        if any(needle in _cell_text_of(c) for c in row):
            print(when, r, [(round(c.visual_layout.bounding_box.x0 * 595, 1) if c.visual_layout else None,
                             round(c.visual_layout.bounding_box.x1 * 595, 1) if c.visual_layout else None,
                             _cell_text_of(c), (c.metadata or {}).get("leader_after")) for c in row])


def traced(np, pymupdf, page, table):
    print("page width", page.rect.width)
    show(table, "before")
    n = real(np, pymupdf, page, table)
    show(table, "after ")
    return n


analyzer._drop_leaders = traced
_extract_table(pdf)
