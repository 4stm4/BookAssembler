"""Debug-only: are our glyphs the size the source printed?

Measuring this on a scan is easy to get wrong, so the probe measures it
two ways and prints both.

The naive way - dark-pixel extent inside the word's rect, padded a
little - is contaminated on the voltage-regulator fixture, whose value
columns are only ~20pt wide and fenced by vertical rules: a pad of 1pt
reaches the rule, and the rule is counted as glyph ink. The tell was in
the source's own numbers, where "12.5" measured 6.83pt against "Line
Regulation"'s 5.17pt even though the latter carries ascenders AND a
descender and cannot be shorter.

So "raw" is that naive extent, and "clean" drops any pixel row or
column covering more than _RULE_COVER of the crop - a rule crosses its
whole crop, a glyph never does - and uses no padding at all. Where the
two disagree, the raw number was measuring furniture, not type.

Alongside each word: the size its source span reported, what
_snap_size does with it, and the size that WOULD match the source
(snapped / ratio, since rendered ink scales linearly with font size).
Cells that end up at the SAME emitted size but different ratios prove
the reported sizes are not what drives the difference.

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.assembler.latex_builder import (
    build_latex, compile_xelatex, _snap_size, _cell_text,
)
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import _table_texts

_INK = 160
_ZOOM = 6.0
_MAX_WORDS = 12
_RULE_COVER = 0.80


def _ink_mask(pdf_path, page_index, rect, pad):
    doc = fitz.open(str(pdf_path))
    page = doc[page_index]
    clip = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
    pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(_ZOOM, _ZOOM))
    doc.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = (
        (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3
        if pix.n >= 3 else arr[:, :, 0].astype(np.int32)
    )
    return grey < _INK


def ink_height(pdf_path, page_index, rect, pad=1.0, drop_rules=False):
    """Vertical extent of glyph ink, in points, or None."""
    ink = _ink_mask(pdf_path, page_index, rect, pad)
    if drop_rules and ink.size:
        # A rule spans its whole crop; a glyph never does. Drop those
        # rows and columns before measuring what is left.
        keep_rows = ink.mean(axis=1) <= _RULE_COVER
        keep_cols = ink.mean(axis=0) <= _RULE_COVER
        ink = ink[keep_rows][:, keep_cols]
    if not ink.size:
        return None
    rows = np.where(ink.any(axis=1))[0]
    if not len(rows):
        return None
    return (rows[-1] - rows[0] + 1) / _ZOOM


def cell_size_for(table, text):
    for row in table.grid:
        for cell in row:
            if _cell_text(cell).strip() == text:
                style = getattr(getattr(cell, "visual_layout", None), "style", None)
                return getattr(style, "font_size_pt", None) if style else None
    return None


def run(name, fixture):
    print("=" * 92)
    print(name)
    table = _extract_table(fixture)
    texts = _table_texts(table)

    sizes = sorted(
        cell.visual_layout.style.font_size_pt
        for row in table.grid for cell in row
        if cell.visual_layout and cell.visual_layout.style
        and cell.visual_layout.style.font_size_pt
    )
    median_pt = sizes[len(sizes) // 2] if sizes else 0.0
    if sizes:
        print(f"  reported sizes: n={len(sizes)} min={sizes[0]:.2f} "
              f"median={median_pt:.2f} max={sizes[-1]:.2f}")

    doc = KnowledgeDocument(
        title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
    )
    tex = build_latex(doc)
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)

        src_doc, out_doc = fitz.open(str(fixture)), fitz.open(str(pdf))
        src_page, out_page = src_doc[0], out_doc[1]
        rows = []
        for text in [t for t in texts if len(t) >= 4]:
            s_hits, o_hits = src_page.search_for(text), out_page.search_for(text)
            if len(s_hits) != 1 or len(o_hits) != 1:
                continue  # ambiguous: cannot be sure it is the same word
            s_raw = ink_height(fixture, 0, s_hits[0])
            o_raw = ink_height(Path(pdf), 1, o_hits[0])
            s_cl = ink_height(fixture, 0, s_hits[0], pad=0.0, drop_rules=True)
            o_cl = ink_height(Path(pdf), 1, o_hits[0], pad=0.0, drop_rules=True)
            # The one to trust: no padding, no filter. A rule lies
            # outside the word's own rect, so there is nothing to
            # filter out, and nothing can eat the glyph either.
            s_p0 = ink_height(fixture, 0, s_hits[0], pad=0.0)
            o_p0 = ink_height(Path(pdf), 1, o_hits[0], pad=0.0)
            if s_raw and o_raw and s_cl and o_cl and s_p0 and o_p0:
                rows.append((
                    text, s_raw, o_raw, s_cl, o_cl, s_p0, o_p0,
                    cell_size_for(table, text),
                ))
            if len(rows) >= _MAX_WORDS:
                break
        src_doc.close()
        out_doc.close()

    if not rows:
        print("  no unambiguous word found on both pages")
        return

    print("   pad1 ratio | filtered | pad0 src/out  ratio | reported snapped needed  text")
    p0_ratios, needed_all = [], []
    for text, s_raw, o_raw, s_cl, o_cl, s_p0, o_p0, reported in rows:
        r_raw = o_raw / s_raw
        r_cl = o_cl / s_cl
        r_p0 = o_p0 / s_p0
        p0_ratios.append(r_p0)
        snapped = _snap_size(reported, median_pt) if reported else None
        needed = snapped / r_p0 if snapped else None
        if needed:
            needed_all.append(needed)
        print(
            f"  {r_raw:10.3f} | {r_cl:8.3f} | "
            f"{s_p0:6.2f} {o_p0:6.2f} {r_p0:6.3f} | "
            f"{reported or 0.0:7.2f} {snapped or 0.0:7.2f} {needed or 0.0:6.2f}  {text[:22]}"
        )
    p0_ratios.sort()
    print(f"  median pad0 ink ratio rebuild/source: "
          f"{p0_ratios[len(p0_ratios) // 2]:.3f}")
    if needed_all:
        needed_all.sort()
        print(f"  needed size: min={needed_all[0]:.2f} "
              f"median={needed_all[len(needed_all) // 2]:.2f} max={needed_all[-1]:.2f}"
              f"   (table median reported: {median_pt:.2f})")


run("FIXTURE_A (decimal/binary)", FIXTURE_A)
run("FIXTURE_B (voltage regulator)", FIXTURE_B)
