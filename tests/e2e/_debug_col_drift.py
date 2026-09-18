"""Debug-only: measure REAL vertical rule x-positions (not header text x0,
which includes unknown padding) in both source and compiled PDF, to get
an honest relative-position comparison for column boundaries.
Run with python3, not pytest."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import numpy as np
import pymupdf
import fitz

from src.analyzers.table.rules import _rule_runs, _RULE_ZOOM, _RULE_PAD_PT, _RULE_INK_LEVEL, _RULE_SPAN
from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, _extract_table


def find_vertical_rules(pdf_path, page_index, bbox_x0, bbox_y0, bbox_x1, bbox_y1):
    doc = pymupdf.open(pdf_path)
    page = doc[page_index]
    pw, ph = page.rect.width, page.rect.height
    clip = pymupdf.Rect(
        bbox_x0 * pw - _RULE_PAD_PT, bbox_y0 * ph - _RULE_PAD_PT,
        bbox_x1 * pw + _RULE_PAD_PT, bbox_y1 * ph + _RULE_PAD_PT,
    )
    clip = clip & page.rect
    pix = page.get_pixmap(matrix=pymupdf.Matrix(_RULE_ZOOM, _RULE_ZOOM), clip=clip)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < _RULE_INK_LEVEL
    height, width = ink.shape
    vertical = _rule_runs(ink.sum(axis=0) > _RULE_SPAN * height)

    def to_page(run, origin, extent):
        centre = (run[0] + run[1]) / 2.0
        return (origin + centre / _RULE_ZOOM) / extent

    rule_x = sorted(to_page(r, clip.x0, pw) for r in vertical)
    doc.close()
    return rule_x, pw


table = _extract_table(FIXTURE_A)
bb = table.visual_layout.bounding_box

src_rules_frac, src_pw = find_vertical_rules(str(FIXTURE_A), 0, bb.x0, bb.y0, bb.x1, bb.y1)
src_rules_pt = [x * src_pw for x in src_rules_frac]
print("SOURCE rule_x (pt):", [round(x, 2) for x in src_rules_pt])
print("SOURCE bbox x0,x1 (pt):", bb.x0 * src_pw, bb.x1 * src_pw)

doc = KnowledgeDocument(
    title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
)
tex = build_latex(doc)
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)

    out_doc = fitz.open(pdf)
    out_page = out_doc[1]
    out_page_w, out_page_h = out_page.rect.width, out_page.rect.height
    r_dec = out_page.search_for("Decimal")
    r_bin = out_page.search_for("Binary")
    all_hdrs = r_dec + r_bin
    approx_x0 = min(r.x0 for r in all_hdrs) - 10
    approx_x1 = max(r.x1 for r in all_hdrs) + 10
    approx_y0 = min(r.y0 for r in all_hdrs) - 5
    # find last row y1 via a late number
    r_last = out_page.search_for("255")
    approx_y1 = max(r.y1 for r in r_last) + 5 if r_last else approx_y0 + 300
    out_doc.close()

    out_rules_frac, out_pw = find_vertical_rules(
        pdf, 1, approx_x0 / out_page_w, approx_y0 / out_page_h,
        approx_x1 / out_page_w, approx_y1 / out_page_h,
    )
    out_rules_pt = [x * out_pw for x in out_rules_frac]
    print("OUTPUT rule_x (pt):", [round(x, 2) for x in out_rules_pt])
    print("OUTPUT approx table x0,x1 (pt):", approx_x0, approx_x1)

# relative position of each internal rule within its own table width
if src_rules_pt:
    src_w = bb.x1 * src_pw - bb.x0 * src_pw
    print("\nSOURCE relative rule positions:", [round((x - bb.x0 * src_pw) / src_w, 4) for x in src_rules_pt])
if out_rules_pt:
    out_w = approx_x1 - approx_x0
    print("OUTPUT relative rule positions:", [round((x - approx_x0) / out_w, 4) for x in out_rules_pt])
