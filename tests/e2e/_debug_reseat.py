"""Debug-only: why _reseat_stacked_lines does or does not move a stacked
cell's last line - for every cell of several lines in a table fixture,
its column, whether the row below has a cell there, and the two ink
baselines.

python3 tests/e2e/_debug_reseat.py <pdf>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import numpy as np
import pymupdf

import src.analyzers.table.analyzer as A
from src.analyzers.printed import measure_line
from src.analyzers.table import rules as R
from tests.e2e.test_assembled_table_pdf import _extract_table

real = A._reseat_stacked_lines


def spy(np_, fitz_, page, table):
    bins = R._column_bins(table.grid)
    pw, ph = page.rect.width, page.rect.height
    for i, row in enumerate(table.grid[:-1]):
        for cell in row:
            text = R._cell_text_of(cell)
            raw = "\n".join(s.text for b in cell.content for il in getattr(b, "inlines", [])
                            for s in getattr(il, "spans", []) if hasattr(s, "text"))
            if "\n" not in raw:
                continue
            col = R._column_of(cell, bins)
            below = [(R._column_of(c, bins), R._cell_text_of(c)[:20]) for c in table.grid[i + 1]]
            print(f"row {i} col {col} {raw!r}  below {below}  bins {[round(b * pw) for b in bins]}")
            b = cell.visual_layout.bounding_box
            box = fitz_.Rect(b.x0 * pw, b.y0 * ph, b.x1 * pw, b.y1 * ph)
            last = raw.split("\n")[-1].split()
            own = [w for w in page.get_text("words") if box.contains(fitz_.Rect(w[:4]).tl + (0.5, 0.5)) and w[4] in last]
            print("   box", box, "own", [(w[4], [round(v, 1) for v in w[:4]]) for w in own])
            if own:
                lr = fitz_.Rect(min(w[0] for w in own), min(w[1] for w in own), max(w[2] for w in own), max(w[3] for w in own))
                m = measure_line(np_, fitz_, page, lr, raw.split("\n")[-1])
                first = min(table.grid[i + 1], key=R._cell_x0)
                fb = first.visual_layout.bounding_box
                t = measure_line(np_, fitz_, page, fitz_.Rect(fb.x0 * pw, fb.y0 * ph, fb.x1 * pw, fb.y1 * ph), R._cell_text_of(first))
                print("   mine", m and (round(m["baseline"], 1), round(m["height"], 1)), "theirs", t and round(t["baseline"], 1))
    return real(np_, fitz_, page, table)


A._reseat_stacked_lines = spy
_extract_table(Path(sys.argv[1]))
