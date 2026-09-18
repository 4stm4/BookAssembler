"""Debug-only: measure per-row y-position drift between source and
compiled PDF directly, after all row-height fixes, to see exactly where
remaining drift accumulates. Run directly with python3, not pytest."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, _extract_table

table = _extract_table(FIXTURE_A)
doc = KnowledgeDocument(
    title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
)
tex = build_latex(doc)

with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)
    out_doc = fitz.open(pdf)
    out_page = out_doc[1]

    src_doc = fitz.open(FIXTURE_A)
    src_page = src_doc[0]

    labels = [str(n) for n in range(18)]
    print(f"{'n':<4}{'src_y0':>10}{'out_y0':>10}{'src_gap':>10}{'out_gap':>10}")
    prev_s = prev_o = None
    for lbl in labels:
        sr = src_page.search_for(lbl, clip=fitz.Rect(0, 0, src_page.rect.width * 0.4, src_page.rect.height))
        orr = out_page.search_for(lbl, clip=fitz.Rect(0, 0, out_page.rect.width * 0.4, out_page.rect.height))
        if sr and orr:
            sy = sr[0].y0
            oy = orr[0].y0
            sg = (sy - prev_s) if prev_s else 0
            og = (oy - prev_o) if prev_o else 0
            print(f"{lbl:<4}{sy:>10.2f}{oy:>10.2f}{sg:>10.2f}{og:>10.2f}")
            prev_s, prev_o = sy, oy
