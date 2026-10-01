"""Debug-only: each OCR word of a fixture page in a y-range, with what
rules._dots makes of its ink (None = holds a blob bigger than a dot).

python3 tests/e2e/_debug_leader_words.py <pdf> <y0_pt> <y1_pt>
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

from src.analyzers.table.rules import _dots

pdf, y0, y1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
page = pymupdf.open(pdf)[0]
for w in page.get_text("words"):
    if y0 <= (w[1] + w[3]) / 2 <= y1:
        r = pymupdf.Rect(w[:4])
        print(f"{w[0]:7.1f} {w[1]:6.1f} {w[2]:7.1f} {w[3]:6.1f}  h={w[3]-w[1]:4.1f}  dots={_dots(np, pymupdf, page, r, w[3]-w[1])!s:5}  {w[4]!r}")
