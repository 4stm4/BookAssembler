"""The vision fallback's crop of an uploaded book (RFC 0022 §4.4).

An uploaded document's source_uri is "upload://name.pdf" — not a path. The
crop opened it as one, so for every book uploaded through the editor the
fallback found no source and made no call at all: "Programming the Z80",
4456 low-confidence blocks, "Vision fallback done: 0 calls in 0.0s".
"""
import base64
import io

import pytest

pymupdf = pytest.importorskip("pymupdf")
PIL = pytest.importorskip("PIL.Image")

from src.analyzers.vision_fallback.rules import _page_crop_b64  # noqa: E402
from src.krm.models import (  # noqa: E402
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    VisualLayout,
)


@pytest.fixture()
def uploaded(tmp_path, monkeypatch):
    """A book as the upload endpoint stores it: <KAE_SSD_PATH>/<job>/<name>."""
    monkeypatch.setenv("KAE_SSD_PATH", str(tmp_path))
    job_dir = tmp_path / "job-1"
    job_dir.mkdir()
    pdf = pymupdf.open()
    page = pdf.new_page(width=612, height=792)
    page.insert_text((72, 100), "The stack pointer points to the top of the stack.", fontsize=11)
    pdf.save(job_dir / "programming_the_z80.pdf")
    return "upload://programming_the_z80.pdf"


def block(x0=0.05, x1=0.95):
    return ParagraphBlock(visual_layout=VisualLayout(
        bounding_box=NormalizedRect(x0, 0.10, x1, 0.16), page_or_screen_index=0))


def decode(b64):
    return PIL.open(io.BytesIO(base64.b64decode(b64)))


def test_an_uploaded_book_is_found_and_cropped(uploaded):
    b = block()
    doc = KnowledgeDocument(source_uri=uploaded, root_containers=[ContainerUnit(children=[b])])
    crop = _page_crop_b64(doc, b)
    assert crop is not None
    assert decode(crop).format == "JPEG"


def test_a_full_width_crop_is_held_to_the_vision_size_limit(uploaded):
    """~840 px at 150 dpi; past ~900 px Qwen2.5-VL did not answer in 180 s."""
    b = block()
    doc = KnowledgeDocument(source_uri=uploaded, root_containers=[ContainerUnit(children=[b])])
    assert max(decode(_page_crop_b64(doc, b)).size) <= 512


def test_a_missing_source_gives_no_crop(tmp_path, monkeypatch):
    monkeypatch.setenv("KAE_SSD_PATH", str(tmp_path))
    b = block()
    doc = KnowledgeDocument(source_uri="upload://gone.pdf", root_containers=[ContainerUnit(children=[b])])
    assert _page_crop_b64(doc, b) is None
