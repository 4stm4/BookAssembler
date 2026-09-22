"""Debug-only: per-row vertical pitch in POINTS, source vs assembled,
for both fixtures.

The fraction-based drift curve (_debug_fair_row_y.py) says the rows
drift apart by up to 0.012 of the table's height and then snap back
partway down, which rules out a uniform scale error but does not say
WHICH rows are the wrong height. This prints each row's anchor
position and the step from the previous row, in points, on both sides,
so the individual offenders are visible.

Anchors are the longest cell text of 6+ characters in each row, and
the source-side search is clipped to that row's own bbox, so a value
that repeats elsewhere in the table cannot match the wrong row.

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from src.assembler.latex_builder import build_latex, compile_xelatex, _cell_text
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _table_texts, _source_table_rect, _output_table_rect,
)


def row_anchor(row):
    best = None
    for cell in row:
        text = _cell_text(cell).strip()
        if len(text) >= 6 and (best is None or len(text) > len(best)):
            best = text
    return best


def run(name, fixture):
    print("=" * 66)
    table = _extract_table(fixture)
    texts = _table_texts(table)
    doc = KnowledgeDocument(
        title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
    )
    tex = build_latex(doc)
    src_rect = _source_table_rect(fitz, fixture, 0, table)

    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        out_rect = _output_table_rect(fitz, Path(pdf), 1, texts)

        sd = fitz.open(str(fixture))
        sp = sd[0]
        ph = sp.rect.height
        od = fitz.open(pdf)
        op = od[1]

        print(f"{name}: source height {src_rect.height:.1f}pt, "
              f"rebuild height {out_rect.height:.1f}pt "
              f"({out_rect.height / src_rect.height:.3f}x)")
        header = ("row", "anchor", "src y0", "out y0", "src step", "out step", "diff")
        print("  {:<4}{:<22}{:>9}{:>9}{:>10}{:>10}{:>8}".format(*header))

        prev_s = prev_o = None
        drift = 0.0
        for i, row in enumerate(table.grid):
            anchor = row_anchor(row)
            if not anchor:
                continue
            vl = getattr(row[0], "visual_layout", None)
            bbox = getattr(vl, "bounding_box", None) if vl else None
            if bbox is None:
                continue
            clip = fitz.Rect(src_rect.x0, bbox.y0 * ph - 5, src_rect.x1, bbox.y1 * ph + 5)
            s_hits = sp.search_for(anchor, clip=clip)
            o_hits = op.search_for(anchor, clip=out_rect)
            if not s_hits or not o_hits:
                continue
            sy, oy = s_hits[0].y0, o_hits[0].y0
            s_step = (sy - prev_s) if prev_s is not None else 0.0
            o_step = (oy - prev_o) if prev_o is not None else 0.0
            diff = (o_step - s_step) if prev_s is not None else 0.0
            drift += diff
            print("  {:<4}{:<22}{:>9.1f}{:>9.1f}{:>10.1f}{:>10.1f}{:>+8.1f}".format(
                i, anchor[:22], sy, oy, s_step, o_step, diff))
            prev_s, prev_o = sy, oy
        print(f"  cumulative step drift over the table: {drift:+.1f}pt")
        sd.close()
        od.close()


run("FIXTURE_A (decimal/binary)", FIXTURE_A)
run("FIXTURE_B (voltage regulator)", FIXTURE_B)
