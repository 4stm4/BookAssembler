"""Debug-only: check whether the table's top/bottom border lines fall
inside the OFFICIAL test's own crop rects (both source and assembled),
by rendering zoomed strips at the crop edges. Reuses the real test's
own helper functions (_source_table_rect, _output_table_rect) - does
not reimplement the pipeline or the crop math. Run with python3, not
pytest."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, _extract_table
from tests.e2e.test_visual_overlay import _table_texts, _source_table_rect, _output_table_rect

OUT_DIR = Path("/app/debug_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

table = _extract_table(FIXTURE_A)
texts = _table_texts(table)
doc = KnowledgeDocument(
    title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
)
tex = build_latex(doc)
src_rect = _source_table_rect(fitz, FIXTURE_A, 0, table)
print("OFFICIAL src_rect:", src_rect)

with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)
    out_rect = _output_table_rect(fitz, Path(pdf), 1, texts)
    print("OFFICIAL out_rect:", out_rect)

    sd = fitz.open(str(FIXTURE_A))
    sp = sd[0]
    od = fitz.open(str(pdf))
    op = od[1]

    # Zoom just past each crop's own top/bottom edge, source and assembled.
    top_src = fitz.Rect(src_rect.x0, src_rect.y0 - 15, src_rect.x1, src_rect.y0 + 15)
    bot_src = fitz.Rect(src_rect.x0, src_rect.y1 - 15, src_rect.x1, src_rect.y1 + 15)
    top_out = fitz.Rect(out_rect.x0, out_rect.y0 - 15, out_rect.x1, out_rect.y0 + 15)
    bot_out = fitz.Rect(out_rect.x0, out_rect.y1 - 15, out_rect.x1, out_rect.y1 + 15)

    sp.get_pixmap(clip=top_src, matrix=fitz.Matrix(4, 4)).save(OUT_DIR / "official_top_src.png")
    sp.get_pixmap(clip=bot_src, matrix=fitz.Matrix(4, 4)).save(OUT_DIR / "official_bot_src.png")
    op.get_pixmap(clip=top_out, matrix=fitz.Matrix(4, 4)).save(OUT_DIR / "official_top_out.png")
    op.get_pixmap(clip=bot_out, matrix=fitz.Matrix(4, 4)).save(OUT_DIR / "official_bot_out.png")
    print("saved 4 zoom crops")
