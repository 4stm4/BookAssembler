"""E2E: pixel-level visual assert between a source PDF's own table region and
the same table as extracted + reassembled through the real pipeline.

Text assertions (test_krm_roundtrip.py, test_assembled_table_pdf.py) already
check cell content exactly. This checks the thing a text assert can't: does
the assembled table land where the source table actually is, at roughly the
right shape - by rendering both to images, cropping each to its own table's
real bounding box, and diffing the pixels. A structural regression (a row
detected as a separate table stub and glued on out of order, a column
collapsed into the wrong x-position) moves ink far enough to show up as a
falling similarity score even when every individual cell's text still reads
correctly in isolation.

Similarity is 1 - mean_pixel_difference, comparing both images stretched to
a common size (source and assembled use different fonts/DPI/page geometry,
so this is a shape/position check, not pixel-identity). Fixture A's clean
text layer supports a fairly strict floor; fixture B's OWN text layer is a
deliberately noisy OCR transcription bolted onto a clean-looking scan (see
that fixture's module docstring) - our pipeline faithfully reproduces
whatever that layer says, so its floor only asks for the same table SHAPE,
not matching characters.
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


def _similarity(img_a, img_b) -> float:
    import numpy as np
    w = max(img_a.width, img_b.width)
    h = max(img_a.height, img_b.height)
    a = np.array(img_a.resize((w, h)).convert("L"), dtype=float)
    b = np.array(img_b.resize((w, h)).convert("L"), dtype=float)
    return 1.0 - (float(abs(a - b).mean()) / 255.0)


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
    "fixture_path, source_page, min_similarity",
    [
        # Fixture A: clean text layer - a real structural or content
        # regression should be clearly visible as a falling score.
        (FIXTURE_A, 0, 0.80),
        # Fixture B: OCR-noisy text layer by design (see module docstring) -
        # only the table's SHAPE is being checked here, not its characters.
        (FIXTURE_B, 0, 0.55),
    ],
)
def test_table_visual_overlay_matches_source(tmp_path, fixture_path, source_page, min_similarity):
    """Crop the source table and the reassembled table to their own real
    bounding boxes, overlay them, and assert a minimum pixel similarity -
    a genuine visual check, not a text-content one."""
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

    similarity = _similarity(img_source, img_output)
    assert similarity >= min_similarity, (
        f"table visual similarity {similarity:.3f} fell below {min_similarity} - "
        f"the assembled table's shape/position no longer matches the source page"
    )
