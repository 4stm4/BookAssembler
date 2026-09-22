"""Debug-only: per-column horizontal fraction drift for FIXTURE_B using
the FAIR (no test top-padding) assembled crop. Run with python3."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import _table_texts, _source_table_rect

table = _extract_table(FIXTURE_B)
texts = _table_texts(table)
doc = KnowledgeDocument(
    title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
)
tex = build_latex(doc)
src_rect = _source_table_rect(fitz, FIXTURE_B, 0, table)


def _output_table_rect_no_padding(fitz_mod, pdf_path, page_index, texts):
    d = fitz_mod.open(pdf_path)
    page = d[page_index]
    strong = [t for t in texts if len(t) >= 6]
    rects = []
    for t in strong:
        rects.extend(page.search_for(t))
    d.close()
    x0 = min(r.x0 for r in rects)
    y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y1 = max(r.y1 for r in rects)
    return fitz_mod.Rect(x0 - 4, y0 - 2, x1 + 4, y1 + 4)


with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)
    d = fitz.open(pdf)
    p = d[1]
    out_rect = _output_table_rect_no_padding(fitz, Path(pdf), 1, texts)

    sd = fitz.open(str(FIXTURE_B))
    sp = sd[0]
    print(f"{'anchor':<25}{'src_frac':>10}{'out_frac':>10}{'diff':>10}")
    anchors = ["114", "12.0", "12.5", "10", "120", "30", "60", "43", "61", "71"]
    for a in anchors:
        sr = sp.search_for(a, clip=src_rect + (0, -3, 0, 3))
        orr = p.search_for(a, clip=out_rect + (0, -3, 0, 3))
        if sr and orr:
            sf = (sr[0].x0 - src_rect.x0) / src_rect.width
            of = (orr[0].x0 - out_rect.x0) / out_rect.width
            print(f"{a:<25}{sf:>10.3f}{of:>10.3f}{of - sf:>10.3f}")
