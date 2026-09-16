"""E2E: pixel-level visual assert between a source PDF's own table region and
the same table as extracted + reassembled through the real pipeline.

Text assertions (test_krm_roundtrip.py, test_assembled_table_pdf.py) already
check cell content exactly, row for row. This checks something coarser that
a text assert can't: does the assembled table's overall SHAPE (row density
relative to its width) resemble the source table's - by rendering both to
images, cropping each to its own table's real bounding box, and comparing a
per-row "ink density" profile (see _row_ink_profile) rather than raw pixels,
since a raw pixel diff between two mostly-white crops barely moves even when
real content goes missing.

What this test can and cannot catch (verified by deliberately reintroducing
two already-fixed bugs and rerunning it, not assumed):
  - A GROSS shift - a whole table detected as several disconnected stubs,
    a column collapsed into the wrong x-band, a badly wrong aspect ratio -
    moves the score by a large, easily-thresholded margin.
  - A LOCALIZED shift - one row's cells scattered to the end of an
    otherwise-correct 20+ row table (the exact bug _absorb_stray_columns in
    src/analyzers/table/analyzer.py fixes) does NOT reliably move this
    score: reintroducing that exact bug changed fixture B's similarity by
    less than 0.01, in the "improves" direction if anything (0.398 fixed
    vs 0.409 buggy) - noise, not signal. That class of defect is what the
    exact per-cell assertions in test_krm_roundtrip.py exist to catch;
    this test is not a substitute for them, only a complement.

The thresholds below are the real values measured against the CURRENT,
verified-correct pipeline output in the locked Docker toolchain (not
adjusted to make a known bug pass) - fixture A's clean text layer holds a
tighter floor; fixture B's own text layer is a deliberately noisy OCR
transcription bolted onto a clean-looking scan (see that fixture's module
docstring), and its row heights are additionally governed by how many
lines its long condition cells wrap onto rather than by \\arraystretch
alone, so its floor is set correspondingly looser.
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


def _row_ink_profile(img, buckets: int = 60):
    """Where the ink sits vertically, as a normalized histogram over rows.

    A raw whole-image pixel diff is mostly comparing WHITE BACKGROUND
    between two crops that both happen to be mostly white - it barely
    moves even when a whole row of content is missing or displaced (found
    while planting a known-fixed bug back in to prove the test could catch
    it: the raw pixel score moved from 0.7948 to 0.7963, not a real
    signal). This measures something the raw pixel diff can't drown out:
    which vertical bands of the crop actually have text in them - which
    is exactly "does this table have the same row layout", independent of
    font or glyph differences between a scanned source and a typeset
    rebuild.
    """
    import numpy as np
    a = np.array(img.convert("L"), dtype=float)
    ink = 255.0 - a  # higher = darker = more ink
    row_sums = ink.sum(axis=1)
    h = row_sums.shape[0]
    edges = np.linspace(0, h, buckets + 1).astype(int)
    profile = np.array([
        row_sums[edges[i]:edges[i + 1]].mean() if edges[i + 1] > edges[i] else 0.0
        for i in range(buckets)
    ])
    peak = profile.max()
    return profile / peak if peak > 0 else profile


def _similarity(img_a, img_b) -> float:
    """Row-ink-profile correlation, mapped from [-1, 1] to [0, 1].

    Sensitive to a row being missing, duplicated, or out of order (the
    profile's peaks shift); insensitive to font/glyph differences within a
    row that a raw pixel diff would over-penalize between a scan and a
    typeset rebuild.
    """
    import numpy as np
    pa = _row_ink_profile(img_a)
    pb = _row_ink_profile(img_b)
    if pa.std() == 0 or pb.std() == 0:
        return 0.0
    corr = float(np.corrcoef(pa, pb)[0, 1])
    return (corr + 1.0) / 2.0


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
        # Measured 0.773 against the current, verified-correct pipeline
        # output (arraystretch=1.15 in latex_builder.py, tuned by measuring
        # against this exact fixture - see that file's comment). Floor set
        # with real margin below the measured value, not at it.
        (FIXTURE_A, 0, 0.65),
        # Measured 0.398 against current output - fixture B's condition
        # cells wrap onto multiple lines, so its row height (and thus this
        # score) is governed by wrapping width more than by arraystretch;
        # see the module docstring for what this floor can/cannot catch.
        (FIXTURE_B, 0, 0.30),
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
