"""Debug-only: long runs of dark pixels (all channels low) on a fixture
page - where its drawn lines are - rows and columns, in points.

python3 tests/e2e/_debug_dark_runs.py <pdf> [min_len_pt]
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

ZOOM = 3.0
pdf = sys.argv[1]
min_len = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
page = pymupdf.open(pdf)[0]
print("page", page.rect)
pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM))
arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
dark = arr.max(axis=2) < 110


def runs(line):
    padded = np.concatenate(([False], line, [False])).astype(np.int8)
    e = np.flatnonzero(np.diff(padded))
    return [(a, b) for a, b in zip(e[::2], e[1::2]) if b - a >= min_len * ZOOM]


for name, mat in (("rows", dark), ("cols", dark.T)):
    found = [(i, a, b) for i, line in enumerate(mat) for a, b in runs(line)]
    print(name, len(found))
    for i, a, b in found[:60]:
        print(f"  at {i / ZOOM:6.1f}  {a / ZOOM:6.1f}..{b / ZOOM:6.1f}")
for name, rgb in (("green", (0, 255, 0)), ("magenta", (255, 0, 255)), ("yellow", (255, 255, 0)), ("cyan", (0, 255, 255))):
    near = (np.abs(arr.astype(int) - rgb).sum(axis=2) < 120).sum()
    print(name, near)
