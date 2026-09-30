"""Debug-only: how far each column's text sits from its own rule.

Absolute points, no crop normalisation: for every column, the gap from
the rule on its SET side (right for a right-aligned column, left for a
left-aligned one) to the nearest ink of its text, in the source and in
the rebuild. The fair overlay showed fixture A's columns shifted 1-5pt
right; this says whether that is the indent or the frame.

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, _extract_table
from tests.e2e.test_visual_overlay import _source_table_rect, _table_texts

ZOOM = 4.0


def ink(page, rect):
    pix = page.get_pixmap(clip=rect, matrix=pymupdf.Matrix(ZOOM, ZOOM))
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return a[:, :, :3].mean(axis=2) < 160


def verticals(mask, rect):
    cols = np.where(mask.mean(axis=0) > 0.6)[0]
    out, start, prev = [], None, None
    for c in cols:
        if start is None:
            start = prev = c
        elif c - prev > 2:
            out.append((start, prev)); start = prev = c
        else:
            prev = c
    if start is not None:
        out.append((start, prev))
    return [(rect.x0 + a / ZOOM, rect.x0 + (b + 1) / ZOOM) for a, b in out]


def column_gaps(page, rect):
    m = ink(page, rect)
    rules = verticals(m, rect)
    m[:, m.mean(axis=0) > 0.6] = False          # drop the rules
    m[m.mean(axis=1) > 0.6, :] = False
    colsum = m.sum(axis=0)
    xs = rect.x0 + np.arange(m.shape[1]) / ZOOM
    res = []
    for (l0, l1), (r0, r1) in zip(rules, rules[1:]):
        band = (xs > l1 + 0.5) & (xs < r0 - 0.5) & (colsum > 0.015 * m.shape[0])
        if band.any():
            res.append((l1, r0, xs[band].min(), xs[band].max()))
    return rules, res


table = _extract_table(FIXTURE_A)
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]))
src_rect = _source_table_rect(pymupdf, FIXTURE_A, 0, table)
src_rect = pymupdf.Rect(src_rect.x0 - 25, src_rect.y0 + 25, src_rect.x1 + 25, src_rect.y1 - 5)  # below header
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)
    s_doc, o_doc = pymupdf.open(str(FIXTURE_A)), pymupdf.open(pdf)
    texts = [t for t in _table_texts(table) if len(t) >= 6]
    rs = [r for t in texts for r in o_doc[1].search_for(t)]
    o_rect = pymupdf.Rect(min(r.x0 for r in rs) - 30, min(r.y0 for r in rs) + 20,
                          max(r.x1 for r in rs) + 30, max(r.y1 for r in rs))
    for name, page, rect in (("source", s_doc[0], src_rect), ("rebuild", o_doc[1], o_rect)):
        rules, res = column_gaps(page, rect)
        print(f"{name}: {len(rules)} verticals at " + " ".join(f"{(a + b) / 2:.1f}" for a, b in rules))
        for i, (l, r, x0, x1) in enumerate(res):
            print(f"   col {i}: width {r - l:6.2f}  left gap {x0 - l:5.2f}  right gap {r - x1:5.2f}  ink {x1 - x0:6.2f}")
