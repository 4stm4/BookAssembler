"""Debug-only: where each row's text lands in the rebuilt table against the
source, both measured inside their own overlay crops (as
test_visual_overlay cuts them) and put in the source crop's points.

python3 tests/e2e/_debug_row_drift_crop.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import (
    _build_single_table_pdf, _crop_rects,
)

pdf = Path(sys.argv[1])
table = _extract_table(pdf)
with tempfile.TemporaryDirectory() as td:
    out = _build_single_table_pdf(table, td, "drift")
    src_rect, out_rect = _crop_rects(fitz, pdf, 0, Path(out), table)
    src_words = [w for w in fitz.open(pdf)[0].get_text("words") if src_rect.contains(fitz.Rect(w[:4]))]
    out_words = [w for w in fitz.open(out)[1].get_text("words") if out_rect.contains(fitz.Rect(w[:4]))]
print(f"src crop {src_rect}  out crop {out_rect}")
k = src_rect.height / out_rect.height
used = set()
for w in sorted(src_words, key=lambda w: (round(w[1]), w[0])):
    if w[0] > src_rect.x0 + 0.3 * src_rect.width:
        continue                                    # one word per row: its first
    match = next((i for i, o in enumerate(out_words) if i not in used and o[4] == w[4]), None)
    sy = w[3] - src_rect.y0
    if match is None:
        print(f"{sy:7.1f}  {'-':>7}  {'':>6}  {w[4]}")
        continue
    used.add(match)
    oy = (out_words[match][3] - out_rect.y0) * k
    print(f"{sy:7.1f}  {oy:7.1f}  {oy - sy:+6.1f}  {w[4]}")
