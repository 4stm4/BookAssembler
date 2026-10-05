"""Debug-only: one printed line of a fixture page - its OCR words and
boxes, the ink runs rules._ink_words cuts it into, and what each word got.

python3 tests/e2e/_debug_ink_cut.py <pdf> <first word of the line>
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

from src.analyzers.table import rules

pdf, first = sys.argv[1], sys.argv[2]
page = pymupdf.open(pdf)[0]
words = page.get_text("words")
start = next(w for w in words if w[4] == first)
line = sorted((w for w in words if abs((w[1] + w[3]) / 2 - (start[1] + start[3]) / 2) < 3 and w[0] >= start[0] - 1),
              key=lambda w: w[0])
got = rules._ink_words(page, line)
for w, (a, b) in zip(line, got):
    print(f"{w[4]:14s} box {w[0]:6.1f}-{w[2]:6.1f}  ink {a:6.1f}-{b:6.1f}  shift {a - w[0]:+5.1f} {b - w[2]:+5.1f}")
