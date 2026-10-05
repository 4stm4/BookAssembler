"""Debug-only: the source table above the rebuilt one, both cut exactly as
test_visual_overlay cuts them and scaled to the same width.

The mask says WHERE the two disagree; this shows WHAT each side printed
there - which label sits where, which rule is partial.

Run with python3 (argument A or B), not pytest.
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "/app")
import fitz
from PIL import Image
from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _render_crop, _table_texts,
)
from tests.e2e._debug_crops import _output_table_rect, _source_table_rect

ZOOM = 4.0


def run(name, fixture):
    t = _extract_table(fixture)
    src = _render_crop(fitz, fixture, 0, _source_table_rect(fitz, fixture, 0, t), ZOOM)
    tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[t])]))
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = Path(compile_xelatex("t.tex", td))
        out = _render_crop(fitz, pdf, 1, _output_table_rect(fitz, pdf, 1, _table_texts(t)), ZOOM)
    out = out.resize(src.size)
    sheet = Image.new("RGB", (src.width, src.height * 2 + 20), "white")
    sheet.paste(src, (0, 0))
    sheet.paste(out, (0, src.height + 20))
    path = Path("/app/debug_output") / f"source_vs_rebuild_{name.lower()}.png"
    sheet.save(path)
    print(f"{name}: saved {path}")


if __name__ == "__main__":
    which = sys.argv[1:] or ["A", "B"]
    for n, fx in (("A", FIXTURE_A), ("B", FIXTURE_B)):
        if n in which:
            run(n, fx)
