"""Debug-only: per-column width comparison (source vs assembled) for
BOTH fixtures, measured from the tables' own vertical rules.

Measured outer-rule to outer-rule, not from the test's crop rects:
_output_table_rect pads x by +/-4pt and _source_table_rect does not, and
that asymmetry alone fakes a width error on the first and last column
(it did, on the first version of this script - the sign of the error on
both edge columns came out inverted).

Also prints every vertical rule found in a strip widened well past the
table, so it is visible whether anything foreign (a neighbouring table,
body text) sits close enough that widening _RULE_PAD_PT in
src/analyzers/table/rules.py would sweep it in by mistake.

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _table_texts, _source_table_rect, _output_table_rect,
)

_INK = 160
_PAD = 30.0  # pt of extra width scanned on each side


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
    density_by_col = ink.mean(axis=0)
    cols = np.where(density_by_col > density)[0]
    rules = []
    if len(cols):
        start = prev = cols[0]
        for c in cols[1:]:
            if c - prev > 2:
                rules.append((start + prev) / 2.0)
                start = c
            prev = c
        rules.append((start + prev) / 2.0)
    return [wide.x0 + r / zoom for r in rules]


def widths(rs):
    span = rs[-1] - rs[0]
    w = [rs[i + 1] - rs[i] for i in range(len(rs) - 1)]
    return span, w, [x / span for x in w]


def run(name, fixture, page_index=0):
    print("=" * 60)
    print(name)
    table = _extract_table(fixture)
    texts = _table_texts(table)
    doc = KnowledgeDocument(
        title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
    )
    tex = build_latex(doc)
    src_rect = _source_table_rect(fitz, fixture, page_index, table)

    d = fitz.open(str(fixture))
    pw = d[page_index].rect.width
    d.close()
    bb = table.visual_layout.bounding_box
    md = getattr(table, "metadata", None) or {}
    print(f"  bb.x0={bb.x0 * pw:.1f}pt  bb.x1={bb.x1 * pw:.1f}pt")
    rx = md.get("column_rule_x")
    if rx:
        print(f"  stored column_rule_x: {[round(x * pw, 1) for x in rx]}")

    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        out_rect = _output_table_rect(fitz, Path(pdf), 1, texts)

        s_rules = rules_pt(fixture, page_index, src_rect)
        o_rules = rules_pt(Path(pdf), 1, out_rect)

    print(f"  SOURCE    rules ({len(s_rules)}): {[round(r, 1) for r in s_rules]}")
    print(f"  ASSEMBLED rules ({len(o_rules)}): {[round(r, 1) for r in o_rules]}")

    if len(s_rules) < 2 or len(o_rules) < 2:
        print("  not enough rules to compare")
        return
    s_span, s_w, s_f = widths(s_rules)
    o_span, o_w, o_f = widths(o_rules)
    print(f"  SOURCE    span {s_span:.1f}pt, col widths {[round(x, 1) for x in s_w]}")
    print(f"  ASSEMBLED span {o_span:.1f}pt, col widths {[round(x, 1) for x in o_w]}")
    if len(s_f) != len(o_f):
        print(f"  column count differs: src {len(s_f)} vs out {len(o_f)} - not comparable")
        return
    print("  per-column (fraction of each table's own full width):")
    for i, (a, b) in enumerate(zip(s_f, o_f)):
        print(f"    col {i}: src {a:.4f}  out {b:.4f}  diff {b - a:+.4f}"
              f"  ({(b - a) * s_span:+.1f}pt at source scale)")


run("FIXTURE_A (decimal/binary)", FIXTURE_A)
run("FIXTURE_B (voltage regulator)", FIXTURE_B)
