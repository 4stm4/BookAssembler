"""Unit tests for FontStatsAnalyzer."""

import pytest

from src.analyzers.font_stats import FontFingerprint, FontStatsAnalyzer
from src.analyzers.font_stats.rules import _classify_role, _extract_font
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyleDescriptor,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _para(text: str, family: str = "Times", size: float = 12.0,
          bold: bool = False, italic: bool = False) -> ParagraphBlock:
    inline = TextLineInline(spans=[StyledTextSpan(text=text)])
    style = StyleDescriptor(font_family=family, font_size_pt=size,
                            is_bold=bold, is_italic=italic)
    vl = VisualLayout(
        page_or_screen_index=0,
        bounding_box=NormalizedRect(x0=0.1, y0=0.2, x1=0.9, y1=0.3),
        style=style,
    )
    p = ParagraphBlock(inlines=[inline], visual_layout=vl)
    p.extraction_confidence = 0.7
    p.classification_confidence = 0.7
    return p


def _doc(children: list) -> KnowledgeDocument:
    c = ContainerUnit(title="Ch1", level=1, children=children)
    return KnowledgeDocument(title="Test", root_containers=[c])


class TestFontFingerprint:
    def test_extract(self):
        p = _para("text", "Arial", 14.0, bold=True)
        fp = _extract_font(p)
        assert fp is not None
        assert fp.family == "arial"
        assert fp.size == 14.0
        assert fp.bold is True

    def test_no_style(self):
        p = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="x")])])
        assert _extract_font(p) is None


class TestClassifyRole:
    def test_body(self):
        fp = FontFingerprint(family="times", size=12.0, bold=False, italic=False)
        assert _classify_role(fp, "times", 12.0) == "body"

    def test_heading_larger(self):
        fp = FontFingerprint(family="times", size=16.0, bold=True, italic=False)
        assert _classify_role(fp, "times", 12.0) == "heading"

    def test_caption_smaller(self):
        fp = FontFingerprint(family="times", size=10.0, bold=False, italic=False)
        assert _classify_role(fp, "times", 12.0) == "caption"

    def test_footnote_much_smaller(self):
        fp = FontFingerprint(family="times", size=8.0, bold=False, italic=False)
        assert _classify_role(fp, "times", 12.0) == "footnote"

    def test_code_mono(self):
        fp = FontFingerprint(family="courier new", size=10.0, bold=False, italic=False)
        assert _classify_role(fp, "times", 12.0) == "code"

    def test_math_font(self):
        fp = FontFingerprint(family="cmmi10", size=12.0, bold=False, italic=True)
        assert _classify_role(fp, "times", 12.0) == "math"

    def test_bold_same_size_heading(self):
        fp = FontFingerprint(family="times", size=12.0, bold=True, italic=False)
        assert _classify_role(fp, "times", 12.0) == "heading"


class TestFontStatsAnalyzer:
    def test_basic_stats(self):
        doc = _doc([
            _para("Body text 1.", "Times", 12.0),
            _para("Body text 2.", "Times", 12.0),
            _para("Body text 3.", "Times", 12.0),
            _para("Heading", "Times", 18.0, bold=True),
            _para("Caption", "Times", 9.0),
        ])
        analyzer = FontStatsAnalyzer()
        analyzer.run(doc, ReadingGraph(), KnowledgeGraph())

        stats = doc.metadata["font_stats"]
        assert stats["body_family"] == "times"
        assert stats["body_size"] == 12.0
        assert stats["unique_fonts"] >= 3

    def test_font_roles_assigned(self):
        doc = _doc([
            _para("Body.", "Times", 12.0),
            _para("Body 2.", "Times", 12.0),
            _para("Body 3.", "Times", 12.0),
            _para("Title", "Times", 20.0, bold=True),
            _para("Small note", "Times", 8.0),
            _para("code snippet", "Courier New", 10.0),
        ])
        analyzer = FontStatsAnalyzer()
        analyzer.run(doc, ReadingGraph(), KnowledgeGraph())

        children = doc.root_containers[0].children
        assert children[0].metadata["font_role"] == "body"
        assert children[3].metadata["font_role"] == "heading"
        assert children[4].metadata["font_role"] == "footnote"
        assert children[5].metadata["font_role"] == "code"

    def test_no_font_info(self):
        p = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="x")])])
        doc = _doc([p])
        analyzer = FontStatsAnalyzer()
        analyzer.run(doc, ReadingGraph(), KnowledgeGraph())
        assert "font_stats" not in (doc.metadata or {})

    def test_tombstoned_excluded(self):
        p = _para("tombstoned", "Times", 12.0)
        p.is_tombstoned = True
        doc = _doc([p, _para("alive", "Times", 12.0)])
        analyzer = FontStatsAnalyzer()
        analyzer.run(doc, ReadingGraph(), KnowledgeGraph())
        stats = doc.metadata["font_stats"]
        assert stats["total_blocks_with_font"] == 1
