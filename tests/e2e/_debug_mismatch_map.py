"""Debug-only: where a fixture's overlay mismatch comes from - the share of
the mask's pixels that disagree, by horizontal band and by column band,
split into ink only the source has and ink only the rebuild has. Uses the
overlay test's own crops and mask.

python3 tests/e2e/_debug_mismatch_map.py <pdf> [bands]
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import (
    _build_single_table_pdf, _ink_mask, _output_table_rect, _render_crop, _source_table_rect, _table_texts,
)

pdf = Path(sys.argv[1])
bands = int(sys.argv[2]) if len(sys.argv) > 2 else 12
table = _extract_table(pdf)
with tempfile.TemporaryDirectory() as td:
    out = Path(_build_single_table_pdf(table, td, "map"))
    a = _ink_mask(_render_crop(fitz, pdf, 0, _source_table_rect(fitz, pdf, 0, table)))
    b = _ink_mask(_render_crop(fitz, out, 1, _output_table_rect(fitz, out, 1, _table_texts(table))))
total = a.size
print(f"mismatch {(a ^ b).sum() / total:.2%}  source-only {(a & ~b).sum() / total:.2%}  rebuild-only {(b & ~a).sum() / total:.2%}")
print(f"ink: source {a.sum() / total:.2%}  rebuild {b.sum() / total:.2%}  both {(a & b).sum() / total:.2%}")
h, w = a.shape
print("rows:")
for k in range(bands):
    s = slice(k * h // bands, (k + 1) * h // bands)
    print(f"  {k:2d}  {((a[s] ^ b[s]).sum()) / total:6.2%}  src-only {((a[s] & ~b[s]).sum()) / total:6.2%}"
          f"  out-only {((b[s] & ~a[s]).sum()) / total:6.2%}")
print("cols:")
for k in range(8):
    s = slice(k * w // 8, (k + 1) * w // 8)
    print(f"  {k:2d}  {((a[:, s] ^ b[:, s]).sum()) / total:6.2%}")
print("shifted (dx, dy) -> mismatch:")
import numpy as np
best = []
for dy in range(-3, 4):
    for dx in range(-3, 4):
        sb = np.roll(np.roll(b, dy, axis=0), dx, axis=1)
        best.append(((a ^ sb).sum() / total, dx, dy))
for m, dx, dy in sorted(best)[:5]:
    print(f"  ({dx:+d}, {dy:+d}) {m:.2%}")
print("best dx per column band:")
h, w = a.shape
for k in range(8):
    s = slice(k * w // 8, (k + 1) * w // 8)
    scores = []
    for dx in range(-4, 5):
        sb = np.roll(b, dx, axis=1)
        scores.append(((a[:, s] ^ sb[:, s]).sum(), dx))
    m, dx = min(scores)
    print(f"  band {k}: dx {dx:+d}  ({m / total:.2%} vs {(a[:, s] ^ b[:, s]).sum() / total:.2%})")


def grown(m, r):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(m, dy, axis=0), dx, axis=1)
    return out


for r in (1, 2):
    far_src = (a & ~grown(b, r)).sum() / total
    far_out = (b & ~grown(a, r)).sum() / total
    print(f"beyond {r}px of the other's ink: source-only {far_src:.2%}  rebuild-only {far_out:.2%}")
