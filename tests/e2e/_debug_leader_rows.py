"""Debug-only: what the leader passes see on a fixture - per row, the cells
before _drop_leaders, whether _find_placeholder_marks called the row a
leader, and the dots _dots counts in each of the row's words.

python3 tests/e2e/_debug_leader_rows.py <pdf> [rows]
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import numpy as np
import pymupdf

import src.analyzers.table.analyzer as A
from src.analyzers.table import rules as R
from tests.e2e.test_assembled_table_pdf import _extract_table

ROWS = int(sys.argv[2]) if len(sys.argv) > 2 else 99
real = A._drop_leaders


def spy(np_, fitz_, page, table):
    pw, ph = page.rect.width, page.rect.height
    words = page.get_text("words")
    for i, row in enumerate(table.grid[:ROWS]):
        cells = sorted(row, key=R._cell_x0)
        print(f"row {i}: " + " | ".join(
            f"{R._cell_text_of(c)!r}{'*' if (c.metadata or {}).get('leader_after') else ''}" for c in cells))
        for c, inside in zip(cells, R._row_words(cells, words, pw, ph)):
            if not inside:
                continue
            b = c.visual_layout.bounding_box
            line_h = (b.y1 - b.y0) * ph
            print("    " + "  ".join(
                f"{w[4]}:{R._dots(np_, fitz_, page, fitz_.Rect(w[:4]), line_h)}" for w in inside))
    return real(np_, fitz_, page, table)


A._drop_leaders = spy
_extract_table(Path(sys.argv[1]))
