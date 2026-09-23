"""Debug-only: do the table BORDERS coincide, weight removed?

The ink overlay cannot answer this. A source rule is 1.3-2.3pt and
ours is LaTeX's 0.4pt default, so at the comparison mask's resolution
the source line covers ~4 pixels and ours less than one - on the
voltage-regulator fixture the detector finds two of the six vertical
rules we actually draw. Red-vs-blue there is a weight difference
reported as a position difference.

So: render both crops at 3x the mask resolution (our hairlines
survive), find each side's rule CENTRES, and draw them as lines of
equal width. Black then means the border landed in the same place,
red means source-only, blue rebuild-only - position alone, with the
weight difference deliberately factored out.

Both sides are cropped the same way (rule-to-rule when the table has
an outer frame, text extent plus equal margins when it does not, with
the same aspect sanity check _debug_rule_overlap_fair.py uses).

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np
from PIL import Image

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _table_texts, _source_table_rect, _output_table_rect,
)

OUT_DIR = Path("/app/debug_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)
_INK = 160
_W, _H = 1200, 1800          # 3x the overlay's own mask
# A rule crosses essentially the WHOLE table; a dense column of text
# does not. 0.45 was too generous and proved it: on the decimal/binary
# fixture it reported 14 vertical "borders" in a rebuild that draws
# five, because that table's binary-digit columns are regular enough
# to ink 45% of the height on their own. Every distance measured
# against those was partly a distance to a phantom line.
_RULE_SHARE = 0.85


def crop_rects(fixture, pdf, table, texts):
    src = _source_table_rect(fitz, fixture, 0, table)
    out = _output_table_rect(fitz, Path(pdf), 1, texts)
    m = 4.0
    s = fitz.Rect(src.x0 - m, src.y0 - m, src.x1 + m, src.y1 + m)
    d = fitz.open(str(pdf))
    p = d[1]
    rects = []
    for t in [x for x in texts if len(x) >= 6]:
        rects.extend(p.search_for(t))
    d.close()
    if rects:
        out = fitz.Rect(
            min(r.x0 for r in rects) - m, min(r.y0 for r in rects) - m,
            max(r.x1 for r in rects) + m, max(r.y1 for r in rects) + m,
        )
    return s, out


def ink_at(pdf_path, page_index, rect):
    d = fitz.open(str(pdf_path))
    p = d[page_index]
    zoom_x = _W / rect.width
    zoom_y = _H / rect.height
    pix = p.get_pixmap(clip=rect, matrix=fitz.Matrix(zoom_x, zoom_y))
    d.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = (
        (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3
        if pix.n >= 3 else arr[:, :, 0].astype(np.int32)
    )
    return grey < _INK


def rule_centres(mask, axis):
    """Centre index of each band of rule-like rows (axis=0) or cols (axis=1)."""
    cover = mask.mean(axis=1) if axis == 0 else mask.mean(axis=0)
    hits = np.where(cover > _RULE_SHARE)[0]
    out = []
    if len(hits):
        start = prev = hits[0]
        for i in hits[1:]:
            if i - prev > 2:
                out.append(int((start + prev) // 2))
                start = i
            prev = i
        out.append(int((start + prev) // 2))
    return out


def run(name, fixture):
    print("=" * 68)
    print(name)
    table = _extract_table(fixture)
    texts = _table_texts(table)
    doc = KnowledgeDocument(
        title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
    )
    tex = build_latex(doc)
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        s_rect, o_rect = crop_rects(fixture, pdf, table, texts)
        ms = ink_at(fixture, 0, s_rect)
        mo = ink_at(Path(pdf), 1, o_rect)

    s_rows, o_rows = rule_centres(ms, 0), rule_centres(mo, 0)
    s_cols, o_cols = rule_centres(ms, 1), rule_centres(mo, 1)
    print(f"  crops: source {s_rect.width:.1f}x{s_rect.height:.1f}, "
          f"rebuild {o_rect.width:.1f}x{o_rect.height:.1f}")
    print(f"  horizontal borders: source {len(s_rows)}, rebuild {len(o_rows)}")
    print(f"  vertical   borders: source {len(s_cols)}, rebuild {len(o_cols)}")

    tol = 6  # 6 px of 1800 ~ 0.3% of the table's height
    for label, a, b, span in (
        ("horizontal", s_rows, o_rows, _H), ("vertical", s_cols, o_cols, _W)
    ):
        matched = [x for x in a if any(abs(x - y) <= tol for y in b)]
        print(f"  {label}: {len(matched)}/{len(a)} source borders have one of "
              f"ours within {tol}px ({tol / span * 100:.1f}% of the span)")
        if a and b:
            offs = [min(abs(x - y) for y in b) for x in a]
            print(f"    raw: worst {max(offs)}px, median {int(np.median(offs))}px")

            # The same comparison with each side measured from its OWN
            # first border instead of from the crop edge. The two crops
            # do not start at the same place - the source's comes from
            # its KRM bbox (which includes the padding the table was
            # printed with) and the rebuild's from its text extent - so
            # a constant offset between them says nothing about the
            # layout. Anchoring both at their first rule removes exactly
            # that, and whatever survives is a real difference in how
            # the grid is spaced.
            a0, b0 = a[0], b[0]
            ra = [x - a0 for x in a]
            rb = [y - b0 for y in b]
            r_off = [min(abs(x - y) for y in rb) for x in ra]
            r_match = len([x for x in r_off if x <= tol])
            print(f"    anchored at each side's first border: "
                  f"{r_match}/{len(ra)} within {tol}px, "
                  f"worst {max(r_off)}px, median {int(np.median(r_off))}px")
            print(f"    constant shift between the two crops: "
                  f"{b0 - a0:+d}px ({(b0 - a0) / span * 100:+.1f}% of the span)")

    # Both sides drawn from their OWN grid origin (first rule), because
    # the two crops do not start at the same place: the source's comes
    # from its KRM bbox, which carries the padding the table was printed
    # with, and the rebuild's from its text extent. That difference is a
    # property of the comparison, not of the layout, and leaving it in
    # shifts every line of one side against the other.
    sy0 = s_rows[0] if s_rows else 0
    sx0 = s_cols[0] if s_cols else 0
    oy0 = o_rows[0] if o_rows else 0
    ox0 = o_cols[0] if o_cols else 0

    img = Image.new("RGB", (_W, _H), "white")
    px = img.load()

    def put(x, y, colour):
        if 0 <= x < _W and 0 <= y < _H:
            px[x, y] = (0, 0, 0) if px[x, y] == (220, 0, 0) else colour

    for y in s_rows:
        for x in range(_W):
            put(x, y - sy0 + 100, (220, 0, 0))
    for x in s_cols:
        for y in range(_H):
            put(x - sx0 + 100, y, (220, 0, 0))
    for y in o_rows:
        for x in range(_W):
            put(x, y - oy0 + 100, (0, 0, 220))
    for x in o_cols:
        for y in range(_H):
            put(x - ox0 + 100, y, (0, 0, 220))
    small = img.resize((600, 900), Image.LANCZOS)
    out = OUT_DIR / f"grid_positions_{name.split()[0].lower()}.png"
    small.save(out)
    print(f"  saved {out}")


run("FIXTURE_A", FIXTURE_A)
run("FIXTURE_B", FIXTURE_B)
