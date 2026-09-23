"""Debug-only: per-row vertical fraction drift for FIXTURE_B using the
FAIR (no test top-padding) assembled crop. Run with python3."""
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
    print(f"{'row':<4}{'anchor':<25}{'src_frac':>10}{'out_frac':>10}{'diff':>10}")
    for i, row in enumerate(table.grid):
        best_text, best_len = None, 0
        for cell in row:
            t = " ".join(
                s.text.strip() for c in cell.content for il in c.inlines for s in il.spans
            )
            if len(t) > best_len and t != "•" and len(t) >= 6:
                best_len, best_text = len(t), t
        if not best_text:
            continue
        sr = sp.search_for(best_text, clip=src_rect + (0, -5, 0, 5))
        orr = p.search_for(best_text, clip=out_rect + (0, -5, 0, 5))
        if sr and orr:
            sf = (sr[0].y0 - src_rect.y0) / src_rect.height
            of = (orr[0].y0 - out_rect.y0) / out_rect.height
            print(f"{i:<4}{best_text[:23]:<25}{sf:>10.3f}{of:>10.3f}{of - sf:>10.3f}")
