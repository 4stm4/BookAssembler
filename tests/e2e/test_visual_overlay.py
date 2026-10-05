"""E2E: pixel-level visual assert between a source PDF's own table region and
the same table as extracted + reassembled through the real pipeline.

Text assertions (test_krm_roundtrip.py, test_assembled_table_pdf.py) already
check cell content exactly, row for row. This checks what no text assert can:
lay the rebuilt table on top of the source table and see whether the ink
actually lands in the same places - by rendering both to images, cropping
each the same way to its own table (text extent grown to its own frame
rules), normalizing them to a common size, and comparing the two
black/white ink matrices pixel by pixel.

The rule: both crops become a black/white ink matrix, one is laid over the
other, and more than MAX_MISMATCH of the ink missing the other's fails the
test.
No per-fixture leniency - a rebuilt table either lands on top of the one it
was extracted from or it does not.

This is deliberately strict, and as of writing the pipeline does NOT pass
it: the reassembled tables overlap their sources by only a few percent of
their ink (IoU 0.066 for fixture A, 0.040 for fixture B, against 1.0 for a
control comparing a crop to itself). The source pages carry structure the
rebuild currently flattens - in fixture B, a `Tj = 25 C` cell spanning two
condition rows, a `with line`/`with load` sub-column inside CHARACTERISTICS,
and CONDITIONS holding its own nested two-row block. A red test here is the
honest state, and the specification for that work.

Three earlier metrics were thrown out for reporting green on visibly
wrong output; see _mask_mismatch for what they were and why they failed.
"""

from pathlib import Path

import pytest

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument, TableBlock
from tests.e2e.test_assembled_table_pdf import (
    FIXTURE_A, FIXTURE_B, FIXTURE_C, FIXTURE_D, FIXTURE_E, _extract_table,
)


def _table_texts(table: TableBlock, min_len: int = 1) -> list:
    texts = []
    for row in table.grid:
        for cell in row:
            for content in cell.content:
                for inline in content.inlines:
                    for span in inline.spans:
                        t = span.text.strip()
                        if len(t) >= min_len:
                            texts.append(t)
    return texts


# Both crops are cut the SAME way: the table's text extent, grown on each
# side to the nearest rule standing within _FRAME_REACH_PT of it (the
# table's own frame, when it draws one), cut through the rule's centre.
# Nothing is added to one side only. The crop used here before gave the
# rebuild alone 4pt of margin left, right and below and max(row_h, 12pt)
# above, while the source got none - which shifted every rebuilt pixel
# against its source counterpart by that margin, so no border could
# coincide however well it was placed.
_FRAME_REACH_PT = 25.0
_FRAME_RULE_SPAN = 0.6   # a rule covers most of the table; text never does


def _grow_to_frame(fitz, page, rect):
    """rect grown on each side to the nearest rule just outside it."""
    import numpy as np
    zoom = 3.0
    clip = fitz.Rect(rect.x0 - _FRAME_REACH_PT, rect.y0 - _FRAME_REACH_PT,
                     rect.x1 + _FRAME_REACH_PT, rect.y1 + _FRAME_REACH_PT) & page.rect
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < _INK_THRESHOLD

    def px(value, origin):
        return int(round((value - origin) * zoom))

    x_lo, x_hi = px(rect.x0, clip.x0), px(rect.x1, clip.x0)
    y_lo, y_hi = px(rect.y0, clip.y0), px(rect.y1, clip.y0)
    rows = np.where(ink[:, x_lo:x_hi].mean(axis=1) > _FRAME_RULE_SPAN)[0]
    cols = np.where(ink[y_lo:y_hi, :].mean(axis=0) > _FRAME_RULE_SPAN)[0]

    def centres(indices, origin):
        runs, start, prev = [], None, None
        for i in indices:
            if start is None:
                start = prev = i
            elif i - prev > 1:
                runs.append((start + prev) / 2.0)
                start = prev = i
            else:
                prev = i
        if start is not None:
            runs.append((start + prev) / 2.0)
        return [origin + r / zoom for r in runs]

    ys = centres(rows, clip.y0)
    xs = centres(cols, clip.x0)
    return fitz.Rect(
        max((x for x in xs if x < rect.x0), default=rect.x0),
        max((y for y in ys if y < rect.y0), default=rect.y0),
        min((x for x in xs if x > rect.x1), default=rect.x1),
        min((y for y in ys if y > rect.y1), default=rect.y1),
    )


def _table_lines(table: TableBlock) -> list:
    """The table's text as the lines it was printed in: a cell of several
    lines is searched for line by line, as a page's text layer holds it."""
    return [line.strip() for t in _table_texts(table) for line in t.split("\n") if line.strip()]


def _table_rect(fitz, pdf_path: Path, page_index: int, texts: list):
    """Locate a table on a page by its own text - the same way on the
    source page and on the assembled one.

    Tokens of 6+ characters the page prints once anchor it - short numbers
    and words, and words the page repeats, risk colliding with unrelated
    text elsewhere on it (the page number, another table, prose). The
    extent then takes in, step by step, every one of the texts found within
    _FRAME_REACH_PT of it, and is grown to its frame.
    """
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    # An anchor is a text the page prints once: on a book page "Decimal"
    # and "Binary" head the decimal/binary table and recur in its prose,
    # and every recurrence stretched the anchor down the page.
    strong = [r for t in texts if len(t) >= 6 for hits in [page.search_for(t)]
              if len({round(h.y0 / 3) for h in hits}) == 1 for r in hits]
    if not strong:
        doc.close()
        return None
    # From the anchor out, a text at a time: whatever of the table's text
    # stands within _FRAME_REACH_PT of what is already in joins it, until
    # nothing more does - a recurrence further down the page never does.
    hits = [r for t in set(texts) for r in page.search_for(t)]
    extent = fitz.Rect(min(r.x0 for r in strong), min(r.y0 for r in strong),
                       max(r.x1 for r in strong), max(r.y1 for r in strong))
    while True:
        near = fitz.Rect(extent.x0 - _FRAME_REACH_PT, extent.y0 - _FRAME_REACH_PT,
                         extent.x1 + _FRAME_REACH_PT, extent.y1 + _FRAME_REACH_PT)
        grown = fitz.Rect(extent)
        for r in hits:
            if near.intersects(r):
                grown |= r
        if grown == extent:
            break
        extent = grown
    rect = _grow_to_frame(fitz, page, extent)
    doc.close()
    return rect


def _crop_rects(fitz, source_pdf: Path, source_page: int, rebuilt_pdf: Path, table: TableBlock):
    """Where to cut the source table and the rebuilt one: both by
    _table_rect, from the lines of the table's text found on BOTH pages.

    The source used to be cut by the table's box as the analyzer recorded
    it and the rebuild by its text, which differ wherever a table's box is
    more than its text: the box-drawn architecture fixture's grid holds
    rows and margins its text does not reach, and its rebuild was cut
    30pt shorter than its source however exactly it was set. One method,
    one set of texts: what each crop holds is decided the same way.
    """
    lines = _table_lines(table)
    src_doc, out_doc = fitz.open(source_pdf), fitz.open(rebuilt_pdf)
    shared = [t for t in dict.fromkeys(lines)
              if src_doc[source_page].search_for(t) and out_doc[1].search_for(t)]
    src_doc.close()
    out_doc.close()
    return _table_rect(fitz, source_pdf, source_page, shared), _table_rect(fitz, rebuilt_pdf, 1, shared)


def _render_crop(fitz, pdf_path: Path, page_index: int, rect, zoom: float = 2.0):
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
    from PIL import Image
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return img


_MASK_SIZE = (400, 600)  # both crops normalized to this before overlaying
_INK_THRESHOLD = 160     # 0-255 grey level below which a pixel counts as ink
# Ink within this many mask pixels of the other crop's ink lands on it. A
# crop laid over itself one pixel to the side disagrees on 42-64% of its
# ink: at 400x600 one pixel is a fraction of a stroke, and no rebuild can
# be placed closer than that to a scan.
_MATCH_REACH_PX = 1

# Share of the ink allowed to miss the other crop's ink. One number for
# every fixture on purpose: a rebuilt table either lands on top of the page
# it came from or it does not, and a per-fixture exception is just a way to
# keep a failing render green.
#
# Raised from 3% to 10% of the crop's area on 2026-09-30, then on
# 2026-10-05 measured against the ink instead of the area and set to 7%,
# both by the maintainer's explicit decision.
MAX_MISMATCH = 0.07


def _ink_mask(img):
    """Binary "there is ink here" mask, normalized to a common size.

    Both crops are stretched to the same size first, so this compares WHERE
    the ink lands within each table, independent of the two documents'
    different page geometry and DPI.
    """
    import numpy as np
    grey = np.array(img.convert("L").resize(_MASK_SIZE), dtype=np.uint8)
    return grey < _INK_THRESHOLD


def _near(mask, reach: int):
    """Every pixel within reach pixels of the mask's ink."""
    import numpy as np
    h, w = mask.shape
    padded = np.pad(mask, reach)
    out = np.zeros_like(mask)
    for dy in range(2 * reach + 1):
        for dx in range(2 * reach + 1):
            out |= padded[dy:dy + h, dx:dx + w]
    return out


def _mask_mismatch(img_a, img_b) -> float:
    """Share of the ink that misses the other crop's ink (0.0 = every
    stroke lands on one).

    Both crops become a black/white matrix, laid one over the other; ink of
    either with no ink of the other within _MATCH_REACH_PX counts as a
    miss, and the misses are taken over the ink of either - not over the
    crop's whole area, which on a sparse page (a typewritten contents list)
    is mostly white the two crops share: there a rebuild that had lost
    every title disagreed on only 9.3% of the area.

    This replaced three earlier metrics that were thrown out for not
    measuring overlay agreement:
      - a raw whole-image pixel diff, which mostly compared the white
        background the two crops share and barely moved when real content
        differed (0.7948 vs 0.7963 with a known bug reintroduced);
      - a per-row ink-density profile correlation, same problem at row
        granularity (0.398 vs 0.409 on that same test);
      - disagreeing pixels over the crop's area, the white-background
        problem again (above).
    Misplaced ink is counted twice, once for being absent where the source
    has it and once for being present where the source does not.
    """
    ma = _ink_mask(img_a)
    mb = _ink_mask(img_b)
    miss = (ma & ~_near(mb, _MATCH_REACH_PX)) | (mb & ~_near(ma, _MATCH_REACH_PX))
    ink = (ma | mb).sum()
    return float(miss.sum()) / float(ink) if ink else 0.0


def _build_single_table_pdf(table: TableBlock, work_dir: str, name: str) -> str:
    import os
    doc = KnowledgeDocument(
        title=name,
        root_containers=[ContainerUnit(title="", level=1, children=[table])],
    )
    tex = build_latex(doc)
    tex_path = os.path.join(work_dir, f"{name}.tex")
    with open(tex_path, "w") as fh:
        fh.write(tex)
    try:
        return compile_xelatex(f"{name}.tex", work_dir)
    except RuntimeError as exc:
        if "not found" in str(exc):
            pytest.skip(
                "local TeX Live is missing a package the preamble needs "
                f"(RFC 0021 SS4) - {exc}"
            )
        raise


@pytest.mark.parametrize(
    "fixture_path, source_page",
    [
        (FIXTURE_A, 0),
        (FIXTURE_B, 0),
        (FIXTURE_C, 0),
        (FIXTURE_D, 0),
        (FIXTURE_E, 0),
    ],
)
def test_table_visual_overlay_matches_source(tmp_path, fixture_path, source_page):
    """Crop the source table and the reassembled table the same way, each
    to its own text extent grown to its frame, lay one ink matrix over
    the other, and fail if more than MAX_MISMATCH of the ink misses."""
    fitz = pytest.importorskip("pymupdf")
    pytest.importorskip("PIL")

    table = _extract_table(fixture_path)

    pdf_path = _build_single_table_pdf(table, str(tmp_path), "overlay_doc")

    src_rect, out_rect = _crop_rects(fitz, fixture_path, source_page, Path(pdf_path), table)
    assert src_rect is not None, "could not locate the source table by its own text"
    assert out_rect is not None, "could not locate the assembled table on its own page"

    img_source = _render_crop(fitz, fixture_path, source_page, src_rect)
    img_output = _render_crop(fitz, Path(pdf_path), 1, out_rect)

    mismatch = _mask_mismatch(img_source, img_output)
    assert mismatch <= MAX_MISMATCH, (
        f"{mismatch:.1%} of the ink misses between the source table and the "
        f"reassembled one (limit {MAX_MISMATCH:.0%}) - overlaid, they do not "
        f"line up: the rebuild is not reproducing the source table's layout"
    )
