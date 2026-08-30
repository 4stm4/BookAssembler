"""Tests for improved TableDetector: separator detection + relaxed thresholds."""

import pytest

from src.analyzers.table_detector import (
    TableDetectorAnalyzer,
    _looks_like_separator,
    _count_columns,
    MIN_TABLE_ROWS,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TableBlock,
    TextLineInline,
    VisualLayout,
)


def _para(text: str, page: int = 0, y0: float = 0.2, y1: float = 0.22) -> ParagraphBlock:
    inline = TextLineInline(spans=[StyledTextSpan(text=text)])
    vl = VisualLayout(
        page_or_screen_index=page,
        bounding_box=NormalizedRect(x0=0.1, y0=y0, x1=0.9, y1=y1),
    )
    p = ParagraphBlock(inlines=[inline], visual_layout=vl)
    p.extraction_confidence = 0.8
    p.classification_confidence = 0.8
    return p


class TestSeparatorDetection:
    def test_dashes(self):
        assert _looks_like_separator("-------------------")

    def test_equals(self):
        assert _looks_like_separator("===================")

    def test_pipes_and_dashes(self):
        assert _looks_like_separator("|---|---|---|")

    def test_unicode_box(self):
        assert _looks_like_separator("─────────────────")

    def test_not_separator_text(self):
        assert not _looks_like_separator("Hello world")

    def test_not_separator_short(self):
        assert not _looks_like_separator("--")


class TestColumnCount:
    def test_tab_separated(self):
        assert _count_columns("Name\tAge\tCity") == 3

    def test_multi_space_separated(self):
        assert _count_columns("Value1    Value2    Value3") == 3

    def test_single_value(self):
        assert _count_columns("Just text") == 1


class TestTableWithSeparators:
    def test_3_row_table_with_separator_detected(self):
        """3 aligned rows with adjacent separator should form a table."""
        step = 0.03
        children = [_para("-------------------", y0=0.17, y1=0.185)]
        for i in range(3):
            y0 = 0.2 + i * step
            children.append(_para(f"Cell {i}", y0=y0, y1=y0 + 0.015))

        container = ContainerUnit(title="Ch1", level=1, children=children)
        doc = KnowledgeDocument(title="Test", root_containers=[container])
        rg, kg = ReadingGraph(), KnowledgeGraph()

        analyzer = TableDetectorAnalyzer()
        analyzer.run(doc, rg, kg)

        tables = [c for c in container.children if isinstance(c, TableBlock)]
        assert len(tables) == 1

    def test_3_short_single_col_blocks_not_table(self):
        """3 short single-word blocks without separators should NOT be a table (diagram labels)."""
        step = 0.03
        children = []
        for i, label in enumerate(["Register", "Datum", "Memory"]):
            y0 = 0.2 + i * step
            children.append(_para(label, y0=y0, y1=y0 + 0.015))

        container = ContainerUnit(title="Ch1", level=1, children=children)
        doc = KnowledgeDocument(title="Test", root_containers=[container])
        rg, kg = ReadingGraph(), KnowledgeGraph()

        analyzer = TableDetectorAnalyzer()
        analyzer.run(doc, rg, kg)

        tables = [c for c in container.children if isinstance(c, TableBlock)]
        assert len(tables) == 0

    def test_separator_tombstoned(self):
        """Separator lines adjacent to tables get tombstoned."""
        step = 0.03
        children = []
        for i in range(4):
            y0 = 0.2 + i * step
            if i == 0:
                children.append(_para("-------------------", y0=y0, y1=y0 + 0.015))
            else:
                children.append(_para(f"Row {i}", y0=y0, y1=y0 + 0.015))

        container = ContainerUnit(title="Ch1", level=1, children=children)
        doc = KnowledgeDocument(title="Test", root_containers=[container])
        rg, kg = ReadingGraph(), KnowledgeGraph()

        analyzer = TableDetectorAnalyzer()
        analyzer.run(doc, rg, kg)

        sep = children[0]
        assert sep.is_tombstoned
