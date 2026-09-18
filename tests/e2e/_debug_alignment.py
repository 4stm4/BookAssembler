"""Debug-only: check whether each column's content hugs its own LEFT or
RIGHT drawn boundary (rule_x), to infer left- vs right-alignment from
real geometry instead of a character-count guess.
Run directly with python3, not pytest."""
import sys

sys.path.insert(0, "/app")

from src.analyzers.table.rules import _mark_cell_borders
from src.assembler.latex_builder import _column_bins
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
import numpy as np
import pymupdf

for name, fx in [("A", FIXTURE_A), ("B", FIXTURE_B)]:
    table = _extract_table(fx)
    source = pymupdf.open(fx)
    _mark_cell_borders(np, pymupdf, source[0], table)
    md = getattr(table, "metadata", None) or {}
    rule_x = md.get("column_rule_x")
    bb = table.visual_layout.bounding_box
    bins = _column_bins(table.grid)
    ncols = len(bins)
    print(f"=== {name} === rule_x={rule_x}")
    if not rule_x or len(rule_x) != ncols - 1:
        print("  no usable rule_x, skipping")
        continue
    boundaries = [bb.x0] + list(rule_x) + [bb.x1]

    col_x0s = {i: [] for i in range(ncols)}
    col_x1s = {i: [] for i in range(ncols)}
    for row in table.grid:
        for cell in row:
            if cell.visual_layout and cell.visual_layout.bounding_box:
                b = cell.visual_layout.bounding_box
                col = min(range(ncols), key=lambda i: abs(bins[i] - b.x0))
                col_x0s[col].append(b.x0)
                col_x1s[col].append(b.x1)

    for i in range(ncols):
        if not col_x0s[i]:
            continue
        avg_x0 = sum(col_x0s[i]) / len(col_x0s[i])
        avg_x1 = sum(col_x1s[i]) / len(col_x1s[i])
        pad_left = avg_x0 - boundaries[i]
        pad_right = boundaries[i + 1] - avg_x1
        label = "LEFT" if pad_left < pad_right else "RIGHT"
        print(f"  col{i}: pad_left={pad_left:.4f} pad_right={pad_right:.4f} -> {label}-aligned")
