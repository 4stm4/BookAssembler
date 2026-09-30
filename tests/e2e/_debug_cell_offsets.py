"""Debug-only: where does fixture A's remaining overlay mismatch come from?

For every word of the table present once on both pages, compares the
ink of that word in the frame the fair overlay uses - each table
normalised to its own text extent (_debug_fair_crop.py) - and reports,
in source points: horizontal and vertical offset of the ink box, and
the ratio of its width and height. Summaries per column and per row
separate the candidates: a column offset is an indent problem, a row
offset a spacing one, a width ratio off 1.0 a typeface one.

Run with python3, not pytest.
"""
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, _extract_table
from tests.e2e.test_visual_overlay import _source_table_rect, _table_texts

ZOOM = 6.0
INK = 160


def ink_box(page, rect):
    """Ink bbox (page pt) inside rect, or None."""
    pix = page.get_pixmap(clip=rect, matrix=pymupdf.Matrix(ZOOM, ZOOM))
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = a[:, :, :3].mean(axis=2) < INK
    # drop full-width/height runs: rules
    ink[ink.mean(axis=1) > 0.8, :] = False
    ink[:, ink.mean(axis=0) > 0.8] = False
    ys, xs = np.nonzero(ink)
    if not len(ys):
        return None
    return (rect.x0 + xs.min() / ZOOM, rect.y0 + ys.min() / ZOOM,
            rect.x0 + (xs.max() + 1) / ZOOM, rect.y0 + (ys.max() + 1) / ZOOM)


def words(page):
    out = defaultdict(list)
    for w in page.get_text("words"):
        out[w[4]].append(pymupdf.Rect(w[:4]))
    return out


table = _extract_table(FIXTURE_A)
texts = _table_texts(table)
doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
tex = build_latex(doc)
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)
    src_doc, out_doc = pymupdf.open(str(FIXTURE_A)), pymupdf.open(pdf)
    sp, op = src_doc[0], out_doc[1]
    s_rect = _source_table_rect(pymupdf, FIXTURE_A, 0, table)
    strong = [t for t in texts if len(t) >= 6]
    rs = [r for t in strong for r in op.search_for(t)]
    o_rect = pymupdf.Rect(min(r.x0 for r in rs), min(r.y0 for r in rs),
                          max(r.x1 for r in rs), max(r.y1 for r in rs))
    sx, sy = s_rect.width / o_rect.width, s_rect.height / o_rect.height
    print(f"crops: source {s_rect.width:.1f}x{s_rect.height:.1f}, rebuild {o_rect.width:.1f}x{o_rect.height:.1f}"
          f"  (rebuild->source scale x{sx:.3f} y{sy:.3f})")

    sw, ow = words(sp), words(op)
    rows = []
    for gi, grow in enumerate(table.grid):
        for ci, cell in enumerate(grow):
            text = " ".join(s.text for p in cell.content for il in p.inlines for s in il.spans).strip()
            if text not in sw or text not in ow or len(sw[text]) != 1 or len(ow[text]) != 1:
                continue
            sb = ink_box(sp, sw[text][0] + (-1.5, -1.5, 1.5, 1.5))
            ob = ink_box(op, ow[text][0] + (-1.5, -1.5, 1.5, 1.5))
            if not sb or not ob:
                continue
            # rebuild box mapped into source coordinates through the fair crop frame
            m = [s_rect.x0 + (ob[0] - o_rect.x0) * sx, s_rect.y0 + (ob[1] - o_rect.y0) * sy,
                 s_rect.x0 + (ob[2] - o_rect.x0) * sx, s_rect.y0 + (ob[3] - o_rect.y0) * sy]
            col = min(range(4), key=lambda k: abs(k - ci))
            rows.append((gi, ci, text, m[0] - sb[0], m[2] - sb[2], m[1] - sb[1], m[3] - sb[3],
                         (m[2] - m[0]) / (sb[2] - sb[0]), (m[3] - m[1]) / (sb[3] - sb[1])))

by_col, by_row = defaultdict(list), defaultdict(list)
for r in rows:
    by_col[r[1]].append(r)
    by_row[r[0]].append(r)
med = lambda v: sorted(v)[len(v) // 2]
print("\ncol  n   dx_left  dx_right  dy_top  dy_bottom  w_ratio  h_ratio   (pt at source scale, median)")
for c in sorted(by_col):
    v = by_col[c]
    print(f"{c:3d} {len(v):3d}  {med([r[3] for r in v]):+7.2f}  {med([r[4] for r in v]):+7.2f}  "
          f"{med([r[5] for r in v]):+6.2f}  {med([r[6] for r in v]):+7.2f}   {med([r[7] for r in v]):6.3f}  {med([r[8] for r in v]):6.3f}")
print("\nrow  n   dy_top  dy_bottom")
for g in sorted(by_row):
    v = by_row[g]
    print(f"{g:3d} {len(v):2d}  {med([r[5] for r in v]):+6.2f}  {med([r[6] for r in v]):+7.2f}   {v[0][2]}")
