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
other, and more than MAX_MISMATCH of the pixels disagreeing fails the test.
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

Two earlier metrics were tried and thrown out for reporting green on this
same visibly-wrong output; see _mask_mismatch for what they were and why
they failed.
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
_FRAME_REACH_PT = 20.0
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


def _source_table_rect(fitz, pdf_path: Path, page_index: int, table: TableBlock):
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pw, ph = page.rect.width, page.rect.height
    bb = table.visual_layout.bounding_box
    rect = _grow_to_frame(fitz, page, fitz.Rect(bb.x0 * pw, bb.y0 * ph, bb.x1 * pw, bb.y1 * ph))
    doc.close()
    return rect


def _output_table_rect(fitz, pdf_path: Path, page_index: int, texts: list):
    """Locate a table on the assembled PDF by its own cell text.

    Tokens of 6+ characters anchor it - short numbers and words risk
    colliding with unrelated text elsewhere on the page (the page number,
    another table). Every cell's text found within _FRAME_REACH_PT of that
    anchor then makes up the table's text extent, the same way the source's
    extent is made of all of its cells.
    """
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    strong = [r for t in texts if len(t) >= 6 for r in page.search_for(t)]
    if not strong:
        doc.close()
        return None
    anchor = fitz.Rect(min(r.x0 for r in strong), min(r.y0 for r in strong),
                       max(r.x1 for r in strong), max(r.y1 for r in strong))
    near = fitz.Rect(anchor.x0 - _FRAME_REACH_PT, anchor.y0 - _FRAME_REACH_PT,
                     anchor.x1 + _FRAME_REACH_PT, anchor.y1 + _FRAME_REACH_PT)
    rects = [r for t in set(texts) for r in page.search_for(t) if near.contains(r)]
    extent = fitz.Rect(min(r.x0 for r in rects), min(r.y0 for r in rects),
                       max(r.x1 for r in rects), max(r.y1 for r in rects))
    rect = _grow_to_frame(fitz, page, extent)
    doc.close()
    return rect


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

# Share of pixels allowed to disagree between the two overlaid ink matrices.
# One number for every fixture on purpose: a rebuilt table either lands on
# top of the page it came from or it does not, and a per-fixture exception
# is just a way to keep a failing render green.
#
# Raised from 3% to 10% on 2026-09-30 by the maintainer's explicit
# decision, together with the symmetric crop above. The rest is glyph
# shape: the source is a scan set in a different face, and its ink edges
# can never coincide pixel for pixel with any font the rebuild sets.
MAX_MISMATCH = 0.10


def _ink_mask(img):
    """Binary "there is ink here" mask, normalized to a common size.

    Both crops are stretched to the same size first, so this compares WHERE
    the ink lands within each table, independent of the two documents'
    different page geometry and DPI.
    """
    import numpy as np
    grey = np.array(img.convert("L").resize(_MASK_SIZE), dtype=np.uint8)
    return grey < _INK_THRESHOLD


def _mask_mismatch(img_a, img_b) -> float:
    """Share of pixels where the two ink masks disagree (0.0 = identical).

    Both crops become a black/white matrix, laid one over the other; every
    pixel where one has ink and the other does not counts as a mismatch.

    This replaced two earlier metrics that were thrown out for not actually
    measuring overlay agreement:
      - a raw whole-image pixel diff, which mostly compared the white
        background the two crops share and barely moved when real content
        differed (0.7948 vs 0.7963 with a known bug reintroduced);
      - a per-row ink-density profile correlation, same problem at row
        granularity (0.398 vs 0.409 on that same test).
    Both let a visibly wrong render pass. This one cannot: misplaced ink is
    counted twice, once for being absent where the source has it and once
    for being present where the source does not.
    """
    ma = _ink_mask(img_a)
    mb = _ink_mask(img_b)
    return float((ma ^ mb).sum()) / float(ma.size)


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
    """Crop the source table and the reassembled table to their own real
    bounding boxes, lay one ink matrix over the other, and fail if more
    than MAX_MISMATCH of the pixels disagree."""
    fitz = pytest.importorskip("pymupdf")
    pytest.importorskip("PIL")

    table = _extract_table(fixture_path)
    texts = _table_texts(table)

    pdf_path = _build_single_table_pdf(table, str(tmp_path), "overlay_doc")

    src_rect = _source_table_rect(fitz, fixture_path, source_page, table)
    out_rect = _output_table_rect(fitz, Path(pdf_path), 1, texts)
    assert out_rect is not None, "could not locate the assembled table on its own page"

    img_source = _render_crop(fitz, fixture_path, source_page, src_rect)
    img_output = _render_crop(fitz, Path(pdf_path), 1, out_rect)

    mismatch = _mask_mismatch(img_source, img_output)
    assert mismatch <= MAX_MISMATCH, (
        f"{mismatch:.1%} of pixels disagree between the source table and the "
        f"reassembled one (limit {MAX_MISMATCH:.0%}) - overlaid, they do not "
        f"line up: the rebuild is not reproducing the source table's layout"
    )
