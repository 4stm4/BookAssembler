"""Debug-only: each leader row's dot pitch as _measure_leader_grid reads
it - first dot, last dot, whole pitches between, the row's estimate.

python3 tests/e2e/_debug_leader_pitch.py <pdf>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import numpy as np
import pymupdf

import src.analyzers.table.analyzer as A
from src.analyzers.table import rules as R
from tests.e2e.test_assembled_table_pdf import _extract_table

real = A._measure_leader_grid


def spy(np_, fitz_, page, table):
    pw, ph = page.rect.width, page.rect.height
    right = table.visual_layout.bounding_box.x1 * pw
    for row in table.grid:
        cells = sorted(row, key=R._cell_x0)
        for cell, nxt in zip(cells, cells[1:] + [None]):
            if not (cell.metadata or {}).get("leader_after"):
                continue
            b = cell.visual_layout.bounding_box
            end = nxt.visual_layout.bounding_box.x0 * pw if nxt is not None else right
            clip = fitz_.Rect(b.x1 * pw, b.y0 * ph, end, b.y1 * ph) & page.rect
            pix = page.get_pixmap(matrix=fitz_.Matrix(R._LEADER_ZOOM, R._LEADER_ZOOM), clip=clip)
            ink = np_.frombuffer(pix.samples, dtype=np_.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].mean(axis=2) < R._RULE_INK_LEVEL
            limit = R._LEADER_DOT_SHARE * (b.y1 - b.y0) * ph * R._LEADER_ZOOM
            xs = sorted(clip.x0 + (min(x for _, x in bl) + max(x for _, x in bl)) / 2 / R._LEADER_ZOOM
                        for bl in R._ink_blobs(np_, ink) if len(bl) >= 2
                        and max(y for y, _ in bl) - min(y for y, _ in bl) + 1 <= limit
                        and max(x for _, x in bl) - min(x for _, x in bl) + 1 <= limit)
            if len(xs) >= 3:
                steps = [round(b2 - a2, 2) for a2, b2 in zip(xs, xs[1:])]
                n = round((xs[-1] - xs[0]) / 6.15)
                print(f"{R._cell_text_of(cell)[:22]!r:26} dots {len(xs):3} span {xs[0]:6.1f}-{xs[-1]:6.1f} n {n:3} est {(xs[-1] - xs[0]) / max(n, 1):.3f}  steps {steps[:6]}")
    return real(np_, fitz_, page, table)


A._measure_leader_grid = spy
_extract_table(Path(sys.argv[1]))
