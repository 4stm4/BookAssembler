"""Debug-only: which part of a fixture's overlay the mismatch sits in (arg: A or B).

Splits the fair overlay's XOR (the same crops and 400x600 masks test_visual_overlay.py
compares) into the header band, the body, and the four column bands, and
reports each region's share of all mismatching pixels. A lever is only
worth pulling where the mismatch actually is.

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _table_texts, _source_table_rect, _output_table_rect, _render_crop, _ink_mask,
)

FIXTURE = FIXTURE_B if (len(sys.argv) > 1 and sys.argv[1].upper() == "B") else FIXTURE_A
table = _extract_table(FIXTURE)
texts = _table_texts(table)
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]))
src_rect = _source_table_rect(fitz, FIXTURE, 0, table)
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)
    out_rect = _output_table_rect(fitz, Path(pdf), 1, texts)
    a = _ink_mask(_render_crop(fitz, FIXTURE, 0, src_rect))
    b = _ink_mask(_render_crop(fitz, Path(pdf), 1, out_rect))

x = a ^ b
H, W = x.shape
total = x.sum()
print(f"mask {W}x{H}, mismatch {total / x.size:.4f}; source ink {a.mean():.3f}, rebuild ink {b.mean():.3f}")
print(f"  red (source only) {(a & ~b).sum() / total:.2%}   blue (rebuild only) {(b & ~a).sum() / total:.2%}")

# header band: rows of the source mask above the first strong horizontal rule
rows_cover = a.mean(axis=1)
rule_rows = np.where(rows_cover > 0.5)[0]
hdr_end = int(rule_rows[0]) + 3 if len(rule_rows) else int(H * 0.08)
print(f"  header band rows 0..{hdr_end}: {x[:hdr_end].sum() / total:.2%} of mismatch "
      f"({x[:hdr_end].mean():.3f} local)")
print(f"  body rows {hdr_end}..{H}: {x[hdr_end:].sum() / total:.2%} ({x[hdr_end:].mean():.3f} local)")

# column bands from the source's vertical rules
cols_cover = a[hdr_end:].mean(axis=0)
vr = np.where(cols_cover > 0.6)[0]
edges = [0]
if len(vr):
    run = [vr[0]]
    for c in vr[1:]:
        if c - run[-1] > 2:
            edges.append(int(np.mean(run))); run = [c]
        else:
            run.append(c)
    edges.append(int(np.mean(run)))
edges.append(W)
edges = sorted(set(edges))
print(f"  column edges (px): {edges}")
for i in range(len(edges) - 1):
    reg = x[hdr_end:, edges[i]:edges[i + 1]]
    print(f"    band {i} x {edges[i]}..{edges[i + 1]}: {reg.sum() / total:.2%} of mismatch ({reg.mean():.3f} local)")
# rule pixels: source rule rows/cols vs rebuild rule rows/cols
src_rule = np.zeros_like(a)
src_rule[rows_cover > 0.5, :] = True
src_rule[:, a.mean(axis=0) > 0.6] = True
out_rule = np.zeros_like(b)
out_rule[b.mean(axis=1) > 0.5, :] = True
out_rule[:, b.mean(axis=0) > 0.6] = True
on_rules = x & (src_rule | out_rule)
print(f"  on rule lines (either side): {on_rules.sum() / total:.2%} of mismatch")
