"""Debug-only: where the rebuild set each word, relative to its table crop.

Run with python3 (argument A, B or a fixture path), not pytest.
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "/app")
import fitz
from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import _crop_rects

arg = (sys.argv[1:] or ["A"])[0]
fx = {"A": FIXTURE_A, "B": FIXTURE_B}.get(arg) or Path(arg)
t = _extract_table(fx)
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[t])]))
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = Path(compile_xelatex("t.tex", td))
    rect = _crop_rects(fitz, fx, 0, pdf, t)[1]
    d = fitz.open(str(pdf))
    for w in d[1].get_text("words"):
        if rect.contains(fitz.Rect(w[:4])):
            print(f"{w[0] - rect.x0:7.2f} {w[1] - rect.y0:7.2f} {w[2] - rect.x0:7.2f} {w[3] - rect.y0:7.2f}  {w[4]}")
