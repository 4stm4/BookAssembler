"""Debug-only: the size of the ink blobs (dots) in a rectangle of a PDF
page, in points - median width and height, and how many.

python3 tests/e2e/_debug_dot_size.py <pdf> <page> <x0> <y0> <x1> <y1>
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

from src.analyzers.table.rules import _ink_blobs

ZOOM = 8.0
pdf, pno = sys.argv[1], int(sys.argv[2])
x0, y0, x1, y1 = (float(v) for v in sys.argv[3:7])
page = pymupdf.open(pdf)[pno]
pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), clip=pymupdf.Rect(x0, y0, x1, y1))
arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
ink = arr[:, :, :3].mean(axis=2) < 160
sizes = []
for blob in _ink_blobs(np, ink):
    ys, xs = [y for y, _ in blob], [x for _, x in blob]
    sizes.append(((max(xs) - min(xs) + 1) / ZOOM, (max(ys) - min(ys) + 1) / ZOOM, len(blob) / ZOOM ** 2))
if sizes:
    w, h, a = (sorted(v)[len(v) // 2] for v in zip(*sizes))
    print(f"{len(sizes)} blobs  median w {w:.2f}pt  h {h:.2f}pt  area {a:.2f}pt2")
