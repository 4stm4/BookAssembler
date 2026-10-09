"""Tests for EphemeraDetectorAnalyzer."""
import pytest

from src.analyzers.ephemera import EphemeraDetectorAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    EphemeraBlock,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _make_para(text: str, y0: float, y1: float, page: int = 0) -> ParagraphBlock:
    span = StyledTextSpan(text=text)
    inline = TextLineInline(spans=[span])
    vl = VisualLayout(
        page_or_screen_index=page,
        bounding_box=NormalizedRect(x0=0.1, y0=y0, x1=0.9, y1=y1),
    )
    return ParagraphBlock(inlines=[inline], visual_layout=vl)


def _run(children):
    container = ContainerUnit(title="Chapter 1", level=1, children=list(children))
    doc = KnowledgeDocument(title="Test", root_containers=[container])
    rg = ReadingGraph()
    kg = KnowledgeGraph()
    EphemeraDetectorAnalyzer().run(doc, rg, kg)
    return container.children


class TestPageNumber:
    def test_digit_top(self):
        result = _run([_make_para("42", 0.02, 0.05)])
        assert len(result) == 1
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "page_number"
        assert result[0].repeated_text == "42"

    def test_digit_bottom(self):
        result = _run([_make_para("7", 0.93, 0.97)])
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "page_number"

    def test_roman_numeral(self):
        result = _run([_make_para("xiv", 0.01, 0.04)])
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "page_number"

    def test_roman_upper(self):
        result = _run([_make_para("XII", 0.95, 0.99)])
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "page_number"

    def test_digit_in_middle_not_promoted(self):
        result = _run([_make_para("42", 0.4, 0.45)])
        assert isinstance(result[0], ParagraphBlock)


class TestHeader:
    def test_short_text_top(self):
        # A running head repeats; the same line on one page only is a page
        # title and stays part of the document.
        result = _run([
            _make_para("Chapter 3", 0.01, 0.04, page=0),
            _make_para("Chapter 3", 0.01, 0.04, page=1),
        ])
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "header"
        assert result[0].repeated_text == "Chapter 3"

    def test_one_off_top_line_is_not_a_header(self):
        result = _run([_make_para("CONTENTS", 0.01, 0.04)])
        assert isinstance(result[0], ParagraphBlock)

    def test_long_text_top_not_promoted(self):
        long_text = "A" * 85
        result = _run([_make_para(long_text, 0.01, 0.04)])
        assert isinstance(result[0], ParagraphBlock)


class TestFooter:
    def test_short_text_bottom(self):
        result = _run([
            _make_para("Copyright 2026", 0.95, 0.99, page=0),
            _make_para("Copyright 2026", 0.95, 0.99, page=1),
        ])
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "footer"

    def test_not_far_enough_bottom(self):
        result = _run([_make_para("Some text", 0.88, 0.92)])
        assert isinstance(result[0], ParagraphBlock)


class TestMixed:
    def test_preserves_body_text(self):
        body = _make_para("Normal paragraph", 0.3, 0.35)
        header = _make_para("Chapter 1", 0.01, 0.04, page=0)
        header2 = _make_para("Chapter 1", 0.01, 0.04, page=1)
        footer = _make_para("5", 0.95, 0.99)
        result = _run([header, body, footer, header2])
        types = [type(r).__name__ for r in result]
        assert types == [
            "EphemeraBlock", "ParagraphBlock", "EphemeraBlock", "EphemeraBlock",
        ]

    def test_no_visual_layout_skipped(self):
        span = StyledTextSpan(text="42")
        inline = TextLineInline(spans=[span])
        p = ParagraphBlock(inlines=[inline])
        result = _run([p])
        assert isinstance(result[0], ParagraphBlock)

    def test_tombstoned_skipped(self):
        p = _make_para("42", 0.01, 0.04)
        p.is_tombstoned = True
        result = _run([p])
        assert isinstance(result[0], ParagraphBlock)
        assert result[0].is_tombstoned

    def test_id_preserved(self):
        p = _make_para("99", 0.01, 0.04)
        original_id = p.id
        result = _run([p])
        assert result[0].id == original_id


def _printed_para(text: str, y0: float, y1: float, lines: list, page: int = 0) -> ParagraphBlock:
    """A scanned page's block, its lines' print read (PrintedLinesAnalyzer)."""
    para = _make_para(text, y0, y1, page)
    para.metadata["printed_lines"] = lines
    return para


def _line(text: str, y0: float, y1: float, size: float = 10.0, bold: bool = False,
          italic: bool = False, words: list = None, page: int = 0) -> dict:
    return {"text": text, "page": page, "box": [0.1, y0, 0.9, y1], "size": size, "bold": bold,
            "italic": italic, "words": words or [], "page_pt": [612.0, 792.0]}


_BODY = "The body of the page runs on in lines of many words like this one."


class TestRunningHeadByPrint:
    """On a scanned page alone nothing repeats: its running head is told by
    its print - at the page's edge, set apart by its case or slant alone,
    or led by the page's number set well apart."""

    def _page(self, head):
        body = []
        for k in range(3):
            y0, y1 = 0.3 + 0.05 * k, 0.33 + 0.05 * k
            body.append(_printed_para(_BODY, y0, y1, [_line(_BODY, y0, y1)]))
        return _run([head] + body)

    def test_capitals_at_the_top_edge_are_a_running_head(self):
        head = _printed_para("PROGRAMMING THE Z80", 0.04, 0.06, [_line("PROGRAMMING THE Z80", 0.04, 0.06)])
        result = self._page(head)
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "header"

    def test_a_bold_heading_at_the_top_edge_stays(self):
        head = _printed_para("A.C. CHARACTERISTICS", 0.04, 0.06,
                             [_line("A.C. CHARACTERISTICS", 0.04, 0.06, bold=True)])
        assert isinstance(self._page(head)[0], ParagraphBlock)

    def test_a_larger_heading_at_the_top_edge_stays(self):
        head = _printed_para("CONTENTS", 0.04, 0.06, [_line("CONTENTS", 0.04, 0.06, size=14.0)])
        assert isinstance(self._page(head)[0], ParagraphBlock)

    def test_body_text_at_the_top_edge_stays(self):
        text = "The move is completed with the microin-"
        head = _printed_para(text, 0.04, 0.06, [_line(text, 0.04, 0.06)])
        assert isinstance(self._page(head)[0], ParagraphBlock)

    def test_a_foot_led_by_the_page_number_set_apart(self):
        words = [[0.09, 0.12, "20"], [0.48, 0.56, "signetics"]]
        foot = _printed_para("20 signetics", 0.95, 0.97, [_line("20 signetics", 0.95, 0.97, words=words)])
        result = self._page(foot)
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "footer"

    def test_a_number_a_word_space_off_is_no_folio(self):
        words = [[0.40, 0.50, "Chapter"], [0.51, 0.52, "3"]]
        foot = _printed_para("Chapter 3", 0.95, 0.97, [_line("Chapter 3", 0.95, 0.97, words=words, bold=True)])
        assert isinstance(self._page(foot)[0], ParagraphBlock)
