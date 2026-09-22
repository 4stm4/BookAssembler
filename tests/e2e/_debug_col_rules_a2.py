"""Debug-only: same column-rule measurement as _debug_col_rules_a.py,
but widened horizontally so the table's OUTER left/right rules land
inside the measured strip too. Comparing rule-to-rule widths as
fractions of the full outer-rule-to-outer-rule span removes the crop
margin artifact (_output_table_rect pads x by +/-4pt, _source_table_rect
does not), which otherwise fakes a width error on the first and last
column. Run with python3, not pytest."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, _extract_table
from tests.e2e.test_visual_overlay import _table_texts, _source_table_rect, _output_table_rect

_INK = 160
_PAD = 30.0  # pt of extra width on each side, to catch the outer rules


def rules_pt(pdf_path, page_index, rect, zoom=4.0, density=0.55):
    wide = fitz.Rect(rect.x0 - _PAD, rect.y0, rect.x1 + _PAD, rect.y1)
    d = fitz.open(str(pdf_path))
    p = d[page_index]
    pix = p.get_pixmap(clip=wide, matrix=fitz.Matrix(zoom, zoom))
    d.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = (
        (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3
        if pix.n >= 3 else arr[:, :, 0].astype(np.int32)
    )
    ink = grey < _INK
    col_density = ink.mean(axis=0)
    cols = np.where(col_density > density)[0]
    rules = []
    if len(cols):
        start = prev = cols[0]
        for c in cols[1:]:
            if c - prev > 2:
                rules.append((start + prev) / 2.0)
                start = c
            prev = c
        rules.append((start + prev) / 2.0)
    # back to absolute page pt
    return [wide.x0 + r / zoom for r in rules]


def report(name, pdf_path, page_index, rect):
    rs = rules_pt(pdf_path, page_index, rect)
    if len(rs) < 2:
        print(f"{name}: only {len(rs)} rules found - {rs}")
        return None
    span = rs[-1] - rs[0]
    widths = [rs[i + 1] - rs[i] for i in range(len(rs) - 1)]
    print(f"{name}: {len(rs)} rules, outer-to-outer span {span:.1f}pt")
    print("   rule x (pt): " + "  ".join(f"{r:.1f}" for r in rs))
    print("   col widths (pt): " + "  ".join(f"{w:.1f}" for w in widths))
    print("   col widths (frac of span): " + "  ".join(f"{w / span:.4f}" for w in widths))
    return [w / span for w in widths], widths, span


table = _extract_table(FIXTURE_A)
texts = _table_texts(table)
doc = KnowledgeDocument(
    title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
)
tex = build_latex(doc)
src_rect = _source_table_rect(fitz, FIXTURE_A, 0, table)

with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)
    out_rect = _output_table_rect(fitz, Path(pdf), 1, texts)

    s = report("SOURCE   ", FIXTURE_A, 0, src_rect)
    o = report("ASSEMBLED", Path(pdf), 1, out_rect)

if s and o and len(s[0]) == len(o[0]):
    print()
    print("per-column comparison (fraction of each table's own full width):")
    for i, (a, b) in enumerate(zip(s[0], o[0])):
        print(f"  col {i}: src {a:.4f}  out {b:.4f}  diff {b - a:+.4f}"
              f"  ({(b - a) * s[2]:+.1f}pt at source scale)")
