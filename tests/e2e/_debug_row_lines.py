"""Debug-only: which cell turns one source row into two rendered lines?

_debug_row_pitch.py says the voltage-regulator fixture's row 3 steps
4.6pt in the source and 13.5pt in the rebuild, while its own emitted
extra is only -0.27pt. So the 13.5pt is that row's NATURAL height, not
space we added - and 13.5 is almost exactly two 6.58pt lines. Something
in it wraps.

Reasoning from the text cannot say which cell: the answer depends on
the p{} width each cell actually lands in. This reads it off the
compiled PDF instead - every text baseline on the assembled page, with
the x range it covers - so a row rendered on two baselines shows both,
and the x range names the column.

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

_Y_TOL = 1.0


def baselines(pdf_path, page_index):
    """(y, x0, x1, text) per rendered text line, top to bottom."""
    doc = fitz.open(str(pdf_path))
    page = doc[page_index]
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if text:
                    spans.append((span["bbox"][1], span["bbox"][0], span["bbox"][2], text))
    doc.close()

    spans.sort(key=lambda s: (s[0], s[1]))
    lines = []
    for y, x0, x1, text in spans:
        if lines and abs(lines[-1][0] - y) <= _Y_TOL:
            lines[-1][1] = min(lines[-1][1], x0)
            lines[-1][2] = max(lines[-1][2], x1)
            lines[-1][3].append((x0, text))
        else:
            lines.append([y, x0, x1, [(x0, text)]])
    return lines


def run(name, fixture):
    print("=" * 76)
    print(name)
    table = _extract_table(fixture)
    doc = KnowledgeDocument(
        title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
    )
    tex = build_latex(doc)
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        lines = baselines(Path(pdf), 1)

    # The SOURCE's own text lines, from its OCR layer. Pixel probes
    # cannot settle where the last line sits relative to the bottom
    # rule: a rule's anti-aliased fringe covers 30-40% of the band and
    # survives a "drop rows covering over half the width" filter, so it
    # reads as ink right up against the rule. Text lines have no fringe.
    bb = table.visual_layout.bounding_box
    _PH = 841.89
    y_lo, y_hi = bb.y0 * _PH - 6.0, bb.y1 * _PH + 6.0
    src_lines = [l for l in baselines(fixture, 0) if y_lo <= l[0] <= y_hi]
    tab_lines = [l for l in lines if l[0] > 40.0]  # drop the page folio
    if src_lines and tab_lines:
        print(f"  SOURCE table lines: {len(src_lines)}  "
              f"first {src_lines[0][0]:.1f}  last {src_lines[-1][0]:.1f}  "
              f"span {src_lines[-1][0] - src_lines[0][0]:.1f}pt")
        print(f"  REBUILD table lines: {len(tab_lines)}  "
              f"first {tab_lines[0][0]:.1f}  last {tab_lines[-1][0]:.1f}  "
              f"span {tab_lines[-1][0] - tab_lines[0][0]:.1f}pt")
        print("   source first: " + " ".join(t for _, t in src_lines[0][3])[:40])
        print("   source last:  " + " ".join(t for _, t in src_lines[-1][3])[:40])
    print(f"  grid rows: {len(table.grid)}   rendered baselines: {len(lines)}")
    print("  line      y   step   x0     x1     cells")
    prev_y = None
    for i, (y, x0, x1, cells) in enumerate(lines):
        step = f"{y - prev_y:5.1f}" if prev_y is not None else "    -"
        prev_y = y
        joined = " | ".join(t for _, t in cells)[:56]
        print(f"  {i:<5} {y:6.1f} {step}  {x0:6.1f} {x1:6.1f}  {joined}")


run("FIXTURE_A (decimal/binary)", FIXTURE_A)
run("FIXTURE_B (voltage regulator)", FIXTURE_B)
