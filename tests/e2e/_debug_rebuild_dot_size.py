"""Debug-only: the size of the leader dots the rebuild set in a fixture's
row, in the name's half of the leader and in the number's (the last 12pt
before the number), in points.

python3 tests/e2e/_debug_rebuild_dot_size.py <pdf> <name, words joined by _> <number>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.analyzers.table.rules import _ink_blobs
from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf

ZOOM = 8.0


def dots(page, rect):
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=rect)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < 160
    sizes = [((max(x for _, x in b) - min(x for _, x in b) + 1) / ZOOM, len(b) / ZOOM ** 2) for b in _ink_blobs(np, ink)]
    w, a = (sorted(v)[len(v) // 2] for v in zip(*sizes))
    return f"{len(sizes)} dots  w {w:.2f}pt  area {a:.2f}pt2"


pdf, name, number = Path(sys.argv[1]), sys.argv[2].replace("_", " "), sys.argv[3]
with tempfile.TemporaryDirectory() as td:
    page = fitz.open(_build_single_table_pdf(_extract_table(pdf), td, "dots"))[1]
    words = page.get_text("words")
    first, second = name.split()[:2]
    y = next(w[3] for a, w in zip(words, words[1:]) if a[4] == first and w[4] == second)
    line = [w for w in words if abs(w[3] - y) < 3]
    name_end = max(w[2] for w in line if w[4] in name.split())
    num_w = max((w for w in line if w[4].lstrip(".") == number), key=lambda w: w[0])
    n = fitz.Rect(0, num_w[1], name_end, num_w[3])
    # the number's word starts with the dots run into it
    num = fitz.Rect(num_w[2] - len(number) * 4.6, num_w[1], num_w[2], num_w[3])
    print("name half  ", dots(page, fitz.Rect(n.x1 + 4, n.y0, num.x0 - 16, n.y1)))
    print("number half", dots(page, fitz.Rect(num.x0 - 12, n.y0, num.x0 - 1, n.y1)))
