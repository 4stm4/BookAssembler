"""Debug-only: find the vertical column rules' real x-positions in
FIXTURE_A's source scan and in our assembled render, by column ink
density (the source is a scan - get_drawings() returns nothing, so the
rules exist only as pixels). Reports each rule as a fraction of the
table's own width so the two can be compared directly.
Run with python3, not pytest."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, _extract_table
from tests.e2e.test_visual_overlay import _table_texts, _source_table_rect, _output_table_rect

_INK = 160


def rule_fracs(pdf_path, page_index, rect, zoom=4.0):
    d = fitz.open(str(pdf_path))
    p = d[page_index]
    pix = p.get_pixmap(clip=rect, matrix=fitz.Matrix(zoom, zoom))
    d.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = (
        (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3
        if pix.n >= 3 else arr[:, :, 0].astype(np.int32)
    )
    ink = grey < _INK
    # A column rule inks nearly every row of the table; glyphs never do.
    col_density = ink.mean(axis=0)
    threshold = 0.6
    cols = np.where(col_density > threshold)[0]
    # group adjacent pixel columns into single rules, take each group's centre
    rules = []
    if len(cols):
        start = prev = cols[0]
        for c in cols[1:]:
            if c - prev > 2:
                rules.append((start + prev) / 2.0)
                start = c
            prev = c
        rules.append((start + prev) / 2.0)
    return [r / pix.width for r in rules], pix.width / zoom


table = _extract_table(FIXTURE_A)
texts = _table_texts(table)
doc = KnowledgeDocument(
    title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
)
tex = build_latex(doc)
src_rect = _source_table_rect(fitz, FIXTURE_A, 0, table)

with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)
    out_rect = _output_table_rect(fitz, Path(pdf), 1, texts)

    src_rules, src_w = rule_fracs(FIXTURE_A, 0, src_rect)
    out_rules, out_w = rule_fracs(Path(pdf), 1, out_rect)

print(f"source table width {src_w:.1f}pt, rules at fractions:")
print("  " + "  ".join(f"{r:.4f}" for r in src_rules))
print(f"assembled table width {out_w:.1f}pt, rules at fractions:")
print("  " + "  ".join(f"{r:.4f}" for r in out_rules))

print()
print("pairwise (same index) source vs assembled:")
for i, (a, b) in enumerate(zip(src_rules, out_rules)):
    print(f"  rule {i}: src {a:.4f}  out {b:.4f}  diff {b - a:+.4f}"
          f"   ({(b - a) * src_w:+.1f}pt of source width)")
