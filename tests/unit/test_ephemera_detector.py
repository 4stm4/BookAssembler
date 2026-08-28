"""Tests for EphemeraDetectorAnalyzer."""
import pytest

from src.analyzers.ephemera_detector import EphemeraDetectorAnalyzer
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


def _make_para(text: str, y0: float, y1: float) -> ParagraphBlock:
    span = StyledTextSpan(text=text)
    inline = TextLineInline(spans=[span])
    vl = VisualLayout(
        page_or_screen_index=0,
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
        result = _run([_make_para("Chapter 3", 0.01, 0.04)])
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "header"
        assert result[0].repeated_text == "Chapter 3"

    def test_long_text_top_not_promoted(self):
        long_text = "A" * 85
        result = _run([_make_para(long_text, 0.01, 0.04)])
        assert isinstance(result[0], ParagraphBlock)


class TestFooter:
    def test_short_text_bottom(self):
        result = _run([_make_para("Copyright 2026", 0.95, 0.99)])
        assert isinstance(result[0], EphemeraBlock)
        assert result[0].ephemera_type == "footer"

    def test_not_far_enough_bottom(self):
        result = _run([_make_para("Some text", 0.88, 0.92)])
        assert isinstance(result[0], ParagraphBlock)


class TestMixed:
    def test_preserves_body_text(self):
        body = _make_para("Normal paragraph", 0.3, 0.35)
        header = _make_para("Chapter 1", 0.01, 0.04)
        footer = _make_para("5", 0.95, 0.99)
        result = _run([header, body, footer])
        types = [type(r).__name__ for r in result]
        assert types == ["EphemeraBlock", "ParagraphBlock", "EphemeraBlock"]

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
