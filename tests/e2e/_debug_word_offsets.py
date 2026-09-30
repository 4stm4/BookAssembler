"""Debug-only: every word of the table, where the source's text layer has
it and where the rebuild set it, both relative to the crop the overlay
test cuts - matched by text, first occurrence to first occurrence.

The source's word boxes are OCR boxes, so a few tenths of a point of
their offsets are the box and not the print; a column of words all off
the same way is placement.

Run with python3 (argument A or B), not pytest.
"""
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, "/app")
import fitz
from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import _output_table_rect, _source_table_rect, _table_texts

fx = FIXTURE_A if (sys.argv[1:] or ["A"])[0] == "A" else FIXTURE_B
t = _extract_table(fx)
src_rect = _source_table_rect(fitz, fx, 0, t)
src = [w for w in fitz.open(str(fx))[0].get_text("words") if src_rect.contains(fitz.Rect(w[:4]))]
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[t])]))
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = Path(compile_xelatex("t.tex", td))
    out_rect = _output_table_rect(fitz, pdf, 1, _table_texts(t))
    out = [w for w in fitz.open(str(pdf))[1].get_text("words") if out_rect.contains(fitz.Rect(w[:4]))]
pool = defaultdict(list)
for w in out:
    pool[w[4]].append(w)
print("word            src x0..x1      rebuild x0..x1   dx0    dx1   dy(centre)")
for w in src:
    if not pool.get(w[4]):
        continue
    o = min(pool[w[4]], key=lambda c: abs((c[1] - out_rect.y0) - (w[1] - src_rect.y0)) + abs((c[0] - out_rect.x0) - (w[0] - src_rect.x0)))
    pool[w[4]].remove(o)
    sx0, sx1 = w[0] - src_rect.x0, w[2] - src_rect.x0
    ox0, ox1 = o[0] - out_rect.x0, o[2] - out_rect.x0
    dy = ((o[1] + o[3]) / 2 - out_rect.y0) - ((w[1] + w[3]) / 2 - src_rect.y0)
    print(f"{w[4][:14]:14s} {sx0:6.1f}..{sx1:6.1f}   {ox0:6.1f}..{ox1:6.1f}  {ox0 - sx0:+5.1f}  {ox1 - sx1:+5.1f}  {dy:+5.1f}")
