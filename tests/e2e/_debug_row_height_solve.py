"""Debug-only: why every row of the decimal/binary fixture steps
~0.4pt taller than its source row.

_debug_row_pitch.py established the shape of the problem: almost every
row's step is +0.4pt (14.7 -> 15.1, 15.2 -> 15.6), compounding to
+13.6pt down the table, plus one gross outlier at row 17 (+4.9pt).
This asks the next question - is dynamic_arraystretch missing its own
target, or is the target itself wrong? - by printing the solve's
inputs beside the height the compiled table actually comes out at,
measured rule-to-rule so no crop padding is mixed in.

Also prints each row's envelope height against its tallest single
cell, to confirm which rows carry a stray mark that inflates them
(row 17 is the suspect: a "*" ellipsis merged in beside "00001111").

Run with python3, not pytest.
"""
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.assembler.latex_builder import build_latex, compile_xelatex, _cell_text
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _table_texts, _source_table_rect, _output_table_rect,
)

_A4_H_CM = 29.7
_PT_PER_CM = 28.3465
_INK = 160


def horizontal_rules(pdf_path, page_index, rect, zoom=4.0, density=0.5):
    """y positions of rules that cross most of the table's width."""
    d = fitz.open(str(pdf_path))
    p = d[page_index]
    wide = fitz.Rect(rect.x0, rect.y0 - 30, rect.x1, rect.y1 + 30)
    pix = p.get_pixmap(clip=wide, matrix=fitz.Matrix(zoom, zoom))
    d.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = (
        (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3
        if pix.n >= 3 else arr[:, :, 0].astype(np.int32)
    )
    ink = grey < _INK
    dens = ink.mean(axis=1)
    rows = np.where(dens > density)[0]
    out = []
    if len(rows):
        start = prev = rows[0]
        for r in rows[1:]:
            if r - prev > 2:
                out.append((start + prev) / 2.0)
                start = r
            prev = r
        out.append((start + prev) / 2.0)
    return [wide.y0 + r / zoom for r in out]


def run(name, fixture):
    print("=" * 66)
    print(name)
    table = _extract_table(fixture)
    bb = table.visual_layout.bounding_box
    texts = _table_texts(table)
    doc = KnowledgeDocument(
        title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
    )
    tex = build_latex(doc)

    m = re.search(r"arraystretch\}\{([0-9.]+)\}", tex)
    stretch = float(m.group(1)) if m else None
    m2 = re.search(r"fontsize\{([0-9.]+)\}\{([0-9.]+)\}", tex)
    font_pt = float(m2.group(1)) if m2 else None

    target_pt = (bb.y1 - bb.y0) * _A4_H_CM * _PT_PER_CM
    base_line = font_pt * 1.2 * stretch if (font_pt and stretch) else None

    print(f"  arraystretch      = {stretch}")
    print(f"  font size         = {font_pt}pt   baselineskip = "
          f"{font_pt * 1.2:.2f}pt" if font_pt else "  font size unknown")
    print(f"  base line (x{stretch}) = {base_line:.2f}pt" if base_line else "")
    print(f"  target height (bbox) = {target_pt:.1f}pt")
    print(f"  grid rows = {len(table.grid)}   "
          f"rows x base line = {len(table.grid) * base_line:.1f}pt"
          if base_line else "")

    src_rect = _source_table_rect(fitz, fixture, 0, table)
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        out_rect = _output_table_rect(fitz, Path(pdf), 1, texts)
        s_rules = horizontal_rules(fixture, 0, src_rect)
        o_rules = horizontal_rules(Path(pdf), 1, out_rect)

    # The rects each side is measured in, and every rule found in them.
    # horizontal_rules() scans a band padded by 30pt, so it can catch a
    # rule OUTSIDE the table: on fixture A the reported rule-to-rule
    # span (364.9pt) is larger than the crop that is supposed to hold
    # the whole table plus margins (358.4pt), which cannot both be true
    # of the same two rules. Printing the positions says which rules are
    # actually being compared.
    print(f"  src_rect  y {src_rect.y0:.1f}..{src_rect.y1:.1f} "
          f"(h {src_rect.height:.1f}pt)  scan band {src_rect.y0 - 30:.1f}.."
          f"{src_rect.y1 + 30:.1f}")
    print(f"  out_rect  y {out_rect.y0:.1f}..{out_rect.y1:.1f} "
          f"(h {out_rect.height:.1f}pt)  scan band {out_rect.y0 - 30:.1f}.."
          f"{out_rect.y1 + 30:.1f}")
    print(f"  source rules ({len(s_rules)}): "
          + " ".join(f"{r:.1f}" for r in s_rules))
    print(f"  rebuild rules ({len(o_rules)}): "
          + " ".join(f"{r:.1f}" for r in o_rules))
    if s_rules:
        print("  source rules, relative to the first: "
              + " ".join(f"{r - s_rules[0]:.1f}" for r in s_rules))
    if o_rules:
        print("  rebuild rules, relative to the first: "
              + " ".join(f"{r - o_rules[0]:.1f}" for r in o_rules))

    if len(s_rules) >= 2 and len(o_rules) >= 2:
        s_h = s_rules[-1] - s_rules[0]
        o_h = o_rules[-1] - o_rules[0]
        print(f"  REAL table height, rule-to-rule: source {s_h:.1f}pt, "
              f"rebuild {o_h:.1f}pt  ({o_h / s_h:.3f}x, {o_h - s_h:+.1f}pt)")
        print(f"  rebuild vs the target the solve aimed at: {o_h - target_pt:+.1f}pt")
    else:
        print(f"  horizontal rules found: source {len(s_rules)}, rebuild {len(o_rules)}"
              " - cannot measure real height")

    heights = []
    for i, row in enumerate(table.grid):
        boxes = [
            c.visual_layout.bounding_box for c in row
            if c.visual_layout and c.visual_layout.bounding_box
        ]
        if not boxes:
            continue
        env = max(b.y1 for b in boxes) - min(b.y0 for b in boxes)
        tallest = max(b.y1 - b.y0 for b in boxes)
        heights.append((i, env, tallest))
    if heights:
        base = min(h[1] for h in heights)
        print(f"  tightest row envelope = {base:.5f} of page height")
        print("  row   envelope   tallest cell   ratio   content")
        for i, env, tallest in heights:
            if env / base > 1.15:
                txt = " ".join(_cell_text(c).strip()[:12] for c in table.grid[i])
                print(f"  {i:<5} {env:.5f}    {tallest:.5f}    {env / base:5.2f}   {txt[:44]}")


run("FIXTURE_A (decimal/binary)", FIXTURE_A)
run("FIXTURE_B (voltage regulator)", FIXTURE_B)
