"""Debug-only: measure each grid row's leading label y0 in both the source
PDF and the assembled PDF, to see whether per-row vertical proportions
match, not just the table's overall bounding box.
Run directly with python3, not pytest."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_B, _extract_table

table = _extract_table(FIXTURE_B)
doc = KnowledgeDocument(
    title="overlay_doc",
    root_containers=[ContainerUnit(title="", level=1, children=[table])],
)
tex = build_latex(doc)

with tempfile.TemporaryDirectory() as td:
    Path(td, "overlay_doc.tex").write_text(tex)
    pdf = compile_xelatex("overlay_doc.tex", td)

    out_doc = fitz.open(pdf)
    out_page = out_doc[1]

    src_doc = fitz.open(FIXTURE_B)
    src_page = src_doc[0]
    pw, ph = src_page.rect.width, src_page.rect.height

    print(f"{'row':<4}{'label':<28}{'src_y0':>10}{'out_y0':>10}")
    src_rows = []
    out_rows = []
    for i, row in enumerate(table.grid):
        if not row:
            continue
        cell = row[0]
        text = " ".join(
            s.text.strip() for c in cell.content for il in c.inlines for s in il.spans
        )
        label = text.strip()
        if len(label) < 5:
            continue
        anchor = label[:20]
        src_rects = src_page.search_for(anchor)
        out_rects = out_page.search_for(anchor)
        sy = round(src_rects[0].y0 / ph, 4) if src_rects else None
        oy = round(out_rects[0].y0, 2) if out_rects else None
        print(f"{i:<4}{label[:26]:<28}{str(sy):>10}{str(oy):>10}")
        if sy is not None:
            src_rows.append((i, sy))
        if oy is not None:
            out_rows.append((i, oy))

    print("\nGaps between consecutive matched rows (src is a fraction of page height, out is in pt):")
    for (i1, s1), (i2, s2) in zip(src_rows, src_rows[1:]):
        pass
    print("src gaps (fraction of page height):")
    for a, b in zip(src_rows, src_rows[1:]):
        print(f"  row {a[0]}->{b[0]}: {b[1]-a[1]:.4f}")
    print("out gaps (pt):")
    for a, b in zip(out_rows, out_rows[1:]):
        print(f"  row {a[0]}->{b[0]}: {b[1]-a[1]:.2f}")
