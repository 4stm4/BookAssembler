"""E2E: pixel-level visual assert between a source PDF's own table region and
the same table as extracted + reassembled through the real pipeline.

Text assertions (test_krm_roundtrip.py, test_assembled_table_pdf.py) already
check cell content exactly, row for row. This checks what no text assert can:
lay the rebuilt table on top of the source table and see whether the ink
actually lands in the same places - by rendering both to images, cropping
each to its own table's real bounding box, normalizing them to a common
size, and comparing the two black/white ink matrices pixel by pixel.

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
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table


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


def _source_table_rect(fitz, pdf_path: Path, page_index: int, table: TableBlock):
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pw, ph = page.rect.width, page.rect.height
    bb = table.visual_layout.bounding_box
    rect = fitz.Rect(bb.x0 * pw, bb.y0 * ph, bb.x1 * pw, bb.y1 * ph)
    doc.close()
    return rect


def _output_table_rect(fitz, pdf_path: Path, page_index: int, texts: list):
    """Locate a table on the assembled PDF by its own distinctive cell text.

    Only tokens of 6+ characters are trusted as anchors - short numbers and
    words risk colliding with unrelated text elsewhere on a page with more
    than one table, the same risk a plain index-based crop would have.
    """
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    strong = [t for t in texts if len(t) >= 6]
    rects = []
    for t in strong:
        rects.extend(page.search_for(t))
    doc.close()
    if not rects:
        return None
    x0 = min(r.x0 for r in rects)
    y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y1 = max(r.y1 for r in rects)
    row_count = max(1, len(set(round(r.y0, 1) for r in rects)))
    row_h = (y1 - y0) / row_count
    return fitz.Rect(x0 - 4, y0 - max(row_h, 12), x1 + 4, y1 + 4)


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
MAX_MISMATCH = 0.03


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
