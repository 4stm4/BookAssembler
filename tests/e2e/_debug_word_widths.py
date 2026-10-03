"""Debug-only: the width of each word in the source against the same word
in the rebuild (first occurrence of each), and their ratio's median.

python3 tests/e2e/_debug_word_widths.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf

pdf = Path(sys.argv[1])
table = _extract_table(pdf)
src = {}
for w in fitz.open(pdf)[0].get_text("words"):
    if len(w[4]) >= 4 and w[4].isalpha():
        src.setdefault(w[4], w[2] - w[0])
with tempfile.TemporaryDirectory() as td:
    out = {}
    for w in fitz.open(_build_single_table_pdf(table, td, "ww"))[1].get_text("words"):
        if w[4] in src:
            out.setdefault(w[4], w[2] - w[0])
ratios = sorted((src[k] / out[k], k) for k in out if out[k] > 0)
for r, k in ratios[:: max(1, len(ratios) // 15)]:
    print(f"{k:16s} src {src[k]:6.1f} out {out[k]:6.1f}  ratio {r:.3f}")
print("median ratio", ratios[len(ratios) // 2][0] if ratios else None, "of", len(ratios))
