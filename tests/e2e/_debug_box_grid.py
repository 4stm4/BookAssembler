"""Debug-only: the box grid boxes._box_grid reads off a fixture page - its
lines and each cell with its span, fill, drawn sides and words.

python3 tests/e2e/_debug_box_grid.py <pdf>
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

from src.analyzers.table.boxes import _box_grid

page = pymupdf.open(sys.argv[1])[0]
grid = _box_grid(np, pymupdf, page)
if grid is None:
    print("no box grid")
    sys.exit()
print("xs", [round(x, 1) for x in grid.xs])
print("ys", [round(y, 1) for y in grid.ys])
for c in grid.cells:
    sides = "".join(s for s, on in zip("TRBL", c.ruled) if on) or "-"
    print(f"r{c.row} c{c.col} {c.row_span}x{c.col_span}  size {c.size:5.2f} stroke {getattr(c, 'stroke', 0):4.2f} bold {getattr(c, 'bold', None)}  fill {c.fill}  ruled {sides:4}  "
          f"{' '.join(w[4] for w in c.words)[:40]!r}")
