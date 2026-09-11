"""The PDF adapter converts text; it does not judge it (RFC 0008 §5.2).

Two ways it used to lose text, both measured on the TOC test books:
  * spaces that the PDF wrote as spans of their own were skipped, gluing
    "Command Line Editing" into "CommandLineEditing" (readline, MetaPost);
  * a "garbage" check dropped blocks outright — every dotted-leader contents
    line and every Cyrillic paragraph without a Latin word went with it.
"""
import io

import pytest

from src.adapters.pdf_adapter import PdfSourceAdapter


def _pdf(draw) -> bytes:
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    draw(doc.new_page())
    data = doc.tobytes()
    doc.close()
    return data


def _texts(raw: bytes):
    doc = PdfSourceAdapter().parse(io.BytesIO(raw), "file://t.pdf")
    return [
        " ".join(s.text for i in (b.inlines or []) for s in i.spans).strip()
        for b in doc.root_containers[0].children
        if getattr(b, "inlines", None)
    ]


def test_spaces_written_as_their_own_spans_are_kept():
    """One span per word, the space between in a different font — so the
    space is a span of its own, as TeX output often has it."""
    fitz = pytest.importorskip("pymupdf")

    def draw(page):
        x = 72
        for word, font in (("Command", "helv"), (" ", "tiro"), ("Line", "helv"),
                           (" ", "tiro"), ("Editing", "helv")):
            page.insert_text((x, 100), word, fontname=font, fontsize=11)
            x += fitz.get_text_length(word, fontname=font, fontsize=11)
    texts = _texts(_pdf(draw))
    assert any("Command Line Editing" in t for t in texts), texts


def test_dotted_leader_line_survives():
    def draw(page):
        page.insert_text((72, 100), "2.1 Mandatory packages " + "." * 60 + " 3")
    texts = _texts(_pdf(draw))
    assert any("Mandatory packages" in t for t in texts), texts


def test_debris_is_emitted_for_an_analyzer_to_judge():
    """Dropping it here left no trace; ScanNoiseAnalyzer tombstones it."""
    def draw(page):
        page.insert_text((72, 100), ", 1IIIIiK,8I ,..i!C\"'-")
    texts = _texts(_pdf(draw))
    assert any("IIIIiK" in t for t in texts), texts
