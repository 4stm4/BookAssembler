"""A scanned page must not be reported as a confidently empty one.

Written after the product showed eight pages of an Intel-3212 datasheet as
BlankPageBlock at 100% confidence. Every unit test passed at the time: they
exercised the analyzers with the agent and the file resolver mocked, so they
said nothing about what the pipeline produces for a real image-only PDF.

This runs the adapter and the full pipeline over a synthetic scan and asserts
on the outcome, which is the level the defect lived at.
"""
import io

import pytest

from src.analyzers import create_default_pipeline
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph


@pytest.fixture(scope="module")
def scanned_pdf() -> bytes:
    """Pages carrying an image and no text layer — what a scan looks like."""
    fitz = pytest.importorskip("pymupdf")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60))
    pix.set_rect(pix.irect, (255, 255, 255))
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_image(fitz.Rect(40, 40, 555, 800), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def _parse(raw: bytes):
    from src.adapters.pdf_adapter import PdfSourceAdapter
    return PdfSourceAdapter().parse(io.BytesIO(raw), "file://scan.pdf")


def _leaves(doc):
    out = []

    def walk(n):
        for c in getattr(n, "children", None) or []:
            walk(c)
        if not hasattr(n, "children"):
            out.append(n)

    for c in doc.root_containers:
        walk(c)
    return out


class TestAdapter:
    def test_unreadable_pages_are_flagged(self, scanned_pdf):
        doc = _parse(scanned_pdf)
        flagged = [n for n in _leaves(doc)
                   if (getattr(n, "metadata", None) or {}).get("needs_ocr")]
        assert len(flagged) == 3, "a scan produced no needs_ocr pages"

    def test_nothing_extracted_is_not_high_confidence(self, scanned_pdf):
        """The UI showed 100% on pages nothing was read from."""
        doc = _parse(scanned_pdf)
        for n in _leaves(doc):
            if (getattr(n, "metadata", None) or {}).get("needs_ocr"):
                assert n.extraction_confidence < 0.5, (
                    "an unread page claims high extraction confidence"
                )
                assert n.confidence_score < 0.5


class TestPipeline:
    """Without a vision agent nothing can be recovered — but the document must
    still say "unread", not "empty"."""

    def _run(self, raw):
        doc = _parse(raw)
        rg, kg = ReadingGraph(), KnowledgeGraph()
        for a in create_default_pipeline():
            if type(a).__name__ in ("LLMRefinementAnalyzer", "PageAgentAnalyzer",
                                    "VisionFallbackAnalyzer", "OCRAnalyzer"):
                continue
            a.run(doc, rg, kg)
        return doc

    def test_scan_pages_do_not_become_blank_pages(self, scanned_pdf):
        doc = self._run(scanned_pdf)
        alive = [n for n in _leaves(doc) if not getattr(n, "is_tombstoned", False)]
        blanks = [n for n in alive if type(n).__name__ == "BlankPageBlock"]
        assert not blanks, (
            "unread scan pages were relabelled BlankPageBlock — that states as "
            "fact that the page has no content, and drops needs_ocr with it"
        )

    def test_the_flag_survives_for_a_later_ocr_run(self, scanned_pdf):
        doc = self._run(scanned_pdf)
        alive = [n for n in _leaves(doc) if not getattr(n, "is_tombstoned", False)]
        still = [n for n in alive
                 if (getattr(n, "metadata", None) or {}).get("needs_ocr")]
        assert still, "needs_ocr was lost, so OCR can never pick these pages up"

    def test_no_page_claims_certainty_about_nothing(self, scanned_pdf):
        doc = self._run(scanned_pdf)
        alive = [n for n in _leaves(doc) if not getattr(n, "is_tombstoned", False)]
        overconfident = [
            n for n in alive
            if getattr(n, "confidence_score", 0) >= 0.9
            and not " ".join(
                s.text for i in (getattr(n, "inlines", None) or [])
                for s in getattr(i, "spans", [])
            ).strip()
        ]
        assert not overconfident, (
            f"{len(overconfident)} empty node(s) reported at >=90% confidence"
        )
