"""Tests for IndexDetectorAnalyzer."""
import pytest

from src.analyzers.index import IndexDetectorAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    IndexEntryBlock,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _make_para(text: str) -> ParagraphBlock:
    span = StyledTextSpan(text=text)
    inline = TextLineInline(spans=[span])
    return ParagraphBlock(inlines=[inline])


def _run(container_title: str, children):
    container = ContainerUnit(title=container_title, level=1, children=list(children))
    doc = KnowledgeDocument(title="Test", root_containers=[container])
    rg = ReadingGraph()
    kg = KnowledgeGraph()
    IndexDetectorAnalyzer().run(doc, rg, kg)
    return container.children


class TestIndexDetection:
    def test_basic_entry(self):
        result = _run("Index", [_make_para("Memory, 12, 45")])
        assert len(result) == 1
        assert isinstance(result[0], IndexEntryBlock)
        assert result[0].term == "Memory"
        assert result[0].page_refs == ["12", "45"]

    def test_range_pages(self):
        result = _run("Index", [_make_para("CPU, 10-15, 30")])
        assert isinstance(result[0], IndexEntryBlock)
        assert result[0].page_refs == ["10-15", "30"]

    def test_russian_title(self):
        result = _run("Указатель", [_make_para("Процессор, 5, 20")])
        assert isinstance(result[0], IndexEntryBlock)
        assert result[0].term == "Процессор"

    def test_predmetny_title(self):
        result = _run("Предметный указатель", [_make_para("Шина, 7")])
        assert isinstance(result[0], IndexEntryBlock)

    def test_non_index_container(self):
        result = _run("Chapter 1", [_make_para("Memory, 12, 45")])
        assert isinstance(result[0], ParagraphBlock)

    def test_non_matching_text(self):
        result = _run("Index", [_make_para("This is regular text.")])
        assert isinstance(result[0], ParagraphBlock)

    def test_id_preserved(self):
        p = _make_para("Term, 1, 2")
        original_id = p.id
        result = _run("Index", [p])
        assert result[0].id == original_id

    def test_mixed_entries(self):
        result = _run("Index", [
            _make_para("Bus, 3, 14"),
            _make_para("Some intro text without page refs"),
            _make_para("Register, 8"),
        ])
        types = [type(r).__name__ for r in result]
        assert types == ["IndexEntryBlock", "ParagraphBlock", "IndexEntryBlock"]
