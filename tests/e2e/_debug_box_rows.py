"""Debug-only: the ink row bands _ink_size reads a box cell's size from,
for the cells whose text holds a given word.

python3 tests/e2e/_debug_box_rows.py <pdf> <word>
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pymupdf

from src.analyzers.table import boxes as B

page = pymupdf.open(sys.argv[1])[0]
grid = B._box_grid(np, pymupdf, page)
z = B._BOX_ZOOM
pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z))
px = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
dark = px.max(axis=2) < B._DARK_LEVEL
for c in grid.cells:
    if not any(sys.argv[2] in w[4] for w in c.words):
        continue
    x0, y0, x1, y1 = (int(v * z) for v in c.rect)
    print("cell", [round(v, 1) for v in c.rect], "size", round(c.size, 2))
    for pad in (3, 6, 9):
        rows = dark[y0 + pad:y1 - pad, x0 + pad:x1 - pad].any(axis=1)
        print("  pad", pad, [(round((y0 + pad + a) / z, 1), round((y0 + pad + b) / z, 1)) for a, b in B._runs(np, rows, 2)])
