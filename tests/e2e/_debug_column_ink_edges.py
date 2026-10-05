"""Debug-only: where each column's ink starts and ends, source against
rebuild, read the same way on both pages inside the crops the overlay
test cuts: between each pair of vertical rules, the first and last pixel
column inked on more than a few rows. Rules and their flanks are the
columns inked down most of the crop.

Run with python3 (argument A or B), not pytest.
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
    _INK_THRESHOLD, _table_texts,
)
from tests.e2e._debug_crops import _output_table_rect, _source_table_rect

ZOOM = 6.0


def edges(pdf, page_index, rect, rule_x, clear):
    """Ink extent of each band between the given vertical rules (page x),
    keeping `clear` points off each rule."""
    d = fitz.open(str(pdf))
    pix = d[page_index].get_pixmap(clip=rect, matrix=fitz.Matrix(ZOOM, ZOOM))
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < _INK_THRESHOLD
    ink = ink[ink.mean(axis=1) < 0.5]                  # drop horizontal rules
    cover = ink.mean(axis=0)
    xs = [rect.x0] + [x for x in rule_x if rect.x0 < x < rect.x1] + [rect.x1]
    out = []
    for k, (l, r) in enumerate(zip(xs, xs[1:])):
        a = int((l - rect.x0 + (clear if k > 0 else 0)) * ZOOM)
        b = int((r - rect.x0 - (clear if k < len(xs) - 2 else 0)) * ZOOM)
        cols = np.nonzero(cover[a:b] > 0.01)[0]
        out.append(((a + cols[0]) / ZOOM, (a + cols[-1] + 1) / ZOOM) if cols.size else None)
    return out


fx = FIXTURE_A if (sys.argv[1:] or ["A"])[0] == "A" else FIXTURE_B
t = _extract_table(fx)
src_rect = _source_table_rect(fitz, fx, 0, t)
W = fitz.open(str(fx))[0].rect.width
src_rules = [x * W for x in t.metadata["column_rule_x"]]
s = edges(fx, 0, src_rect, src_rules, 1.5)
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[t])]))
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = Path(compile_xelatex("t.tex", td))
    out_rect = _output_table_rect(fitz, pdf, 1, _table_texts(t))
    page = fitz.open(str(pdf))[1]
    out_rules = sorted({round((it[1].x + it[2].x) / 2, 1) for dr in page.get_drawings() for it in dr["items"]
                        if it[0] == "l" and abs(it[1].x - it[2].x) < 0.1 and abs(it[1].y - it[2].y) > 20}
                       | {round((dr["rect"].x0 + dr["rect"].x1) / 2, 1) for dr in page.get_drawings()
                          if dr["rect"].width < 3 and dr["rect"].height > 20})
    o = edges(pdf, 1, out_rect, out_rules, 1.5)
print("band   source ink x0..x1    rebuild ink x0..x1    d x0   d x1")
print("rules source:", [round(x - src_rect.x0, 1) for x in src_rules], " rebuild:", [round(x - out_rect.x0, 1) for x in out_rules if out_rect.x0 < x < out_rect.x1])
for i, (a, b) in enumerate(zip(s, o)):
    if a is None or b is None:
        continue
    print(f"{i:3d}   {a[0]:7.1f}..{a[1]:7.1f}    {b[0]:7.1f}..{b[1]:7.1f}    {b[0] - a[0]:+5.1f}  {b[1] - a[1]:+5.1f}")
