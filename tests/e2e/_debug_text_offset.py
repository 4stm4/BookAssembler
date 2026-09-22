"""Debug-only: where the TEXT sits INSIDE its column, source vs
assembled - the defect the masks still show once the columns
themselves land (the right-hand "Decimal" values read as doubled ink,
"32"/"332", while every vertical rule pair has merged).

Two traps this avoids, both hit while getting here:

1. Never measure from a KRM cell bbox. Those are accurate for most
   cells but not all - some binary rows' boxes start ~13pt left of
   where their neighbours' do in the same column. Real glyph rects
   (search_for) are the ground truth.

2. Never call search_for unclipped. "Decimal" and "Binary" each appear
   twice on this page, so an unclipped search returns the FIRST hit
   for both columns and silently compares one column's box against the
   other column's ink (that produced a nonsense dx0=+183.4 before this
   note existed). Every search here is clipped to the column band it
   belongs to.

Reports each anchor's distance from its own column's left rule and to
its right rule, as a fraction of that column's width, in each
document - so the two are comparable despite the slight overall scale
difference between source and rebuild.

Run with python3, not pytest.
"""
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

_INK = 160
_PAD = 30.0


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
    dens = ink.mean(axis=0)
    cols = np.where(dens > density)[0]
    out = []
    if len(cols):
        start = prev = cols[0]
        for c in cols[1:]:
            if c - prev > 2:
                out.append((start + prev) / 2.0)
                start = c
            prev = c
        out.append((start + prev) / 2.0)
    return [wide.x0 + r / zoom for r in out]


def band_of(x, rules):
    for i in range(len(rules) - 1):
        if rules[i] <= x < rules[i + 1]:
            return i
    return None


def find_in_band(page, text, rules, col, y0, y1):
    """search_for restricted to one column band and one row's y range."""
    clip = fitz.Rect(rules[col] - 2, y0, rules[col + 1] + 2, y1)
    hits = page.search_for(text, clip=clip)
    return hits[0] if hits else None


def run(name, fixture):
    print("=" * 62)
    print(name)
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

        s_rules = rules_pt(fixture, 0, src_rect)
        o_rules = rules_pt(Path(pdf), 1, out_rect)
        # A table that draws no outer rules (the voltage-regulator
        # fixture) still gets them in the rebuild, because the rebuilt
        # tabular declares its own left edge. Comparing the two rule
        # lists position-by-position then lines up the source's FIRST
        # internal rule against the rebuild's OUTER one and reports
        # nonsense - so trim the extra rules off the rebuild's ends
        # until both lists describe the same internal boundaries, and
        # say which ones went, since that trimming is a guess about
        # which end is extra and has to stay auditable.
        # Only ONE trim is safe to guess at: a source that drew no outer
        # rules still gets a pair of them in the rebuild, so exactly two
        # extra rules means "drop one from each end". Anything else -
        # notably ONE extra, which is what the voltage-regulator fixture
        # produces - cannot be resolved by guessing which end is the
        # spare. Guessing it (an earlier version dropped the leftmost)
        # lined the source's FIRST INTERNAL rule up against the
        # rebuild's OUTER one and printed a full table of confident,
        # wrong numbers: every anchor fell into "col 0" and read as
        # -25% offset. Refusing is the only honest option there.
        if len(o_rules) == len(s_rules) + 2:
            print(f"  dropped the rebuild's own outer rules "
                  f"({round(o_rules[0], 1)}, {round(o_rules[-1], 1)}) - "
                  f"the source draws none")
            o_rules = o_rules[1:-1]
        if len(s_rules) != len(o_rules) or len(s_rules) < 2:
            print(f"  rule counts differ ({len(s_rules)} source vs "
                  f"{len(o_rules)} rebuild) and which one is spare is a "
                  f"guess - skipping rather than comparing unrelated "
                  f"columns")
            return

        sd = fitz.open(str(fixture))
        sp = sd[0]
        od = fitz.open(str(pdf))
        op = od[1]

        print(f"  source rules: {[round(r,1) for r in s_rules]}")
        print(f"  output rules: {[round(r,1) for r in o_rules]}")
        print(f"  {'anchor':<14}{'col':>4}{'src L%':>8}{'out L%':>8}{'dL%':>7}"
              f"{'src R%':>8}{'out R%':>8}{'dR%':>7}")

        shown = 0
        for row in table.grid:
            for cell in row:
                t = _cell_text(cell).strip()
                if len(t) < 6 or shown >= 10:
                    continue
                vl = getattr(cell, "visual_layout", None)
                cbb = getattr(vl, "bounding_box", None) if vl else None
                if cbb is None:
                    continue
                ph = sp.rect.height
                pw = sp.rect.width
                cx = (cbb.x0 + cbb.x1) / 2.0 * pw
                col = band_of(cx, s_rules)
                if col is None:
                    continue
                sy0, sy1 = cbb.y0 * ph - 4, cbb.y1 * ph + 4
                s_hit = find_in_band(sp, t, s_rules, col, sy0, sy1)
                # same text, same column band, anywhere down the rebuild
                o_hit = find_in_band(op, t, o_rules, col, out_rect.y0 - 5, out_rect.y1 + 5)
                if s_hit is None or o_hit is None:
                    continue
                sw = s_rules[col + 1] - s_rules[col]
                ow = o_rules[col + 1] - o_rules[col]
                sL = (s_hit.x0 - s_rules[col]) / sw * 100
                oL = (o_hit.x0 - o_rules[col]) / ow * 100
                sR = (s_rules[col + 1] - s_hit.x1) / sw * 100
                oR = (o_rules[col + 1] - o_hit.x1) / ow * 100
                print(f"  {t[:14]:<14}{col:>4}{sL:>8.1f}{oL:>8.1f}{oL-sL:>+7.1f}"
                      f"{sR:>8.1f}{oR:>8.1f}{oR-sR:>+7.1f}")
                shown += 1
        sd.close()
        od.close()


run("FIXTURE_A (decimal/binary)", FIXTURE_A)
run("FIXTURE_B (voltage regulator)", FIXTURE_B)
