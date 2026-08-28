"""Tests for AlgorithmDetectorAnalyzer."""
import pytest

from src.analyzers.algorithm_detector import AlgorithmDetectorAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    AlgorithmBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _make_para(text: str) -> ParagraphBlock:
    span = StyledTextSpan(text=text)
    inline = TextLineInline(spans=[span])
    return ParagraphBlock(inlines=[inline])


def _run(children):
    container = ContainerUnit(title="Chapter", level=1, children=list(children))
    doc = KnowledgeDocument(title="Test", root_containers=[container])
    rg = ReadingGraph()
    kg = KnowledgeGraph()
    AlgorithmDetectorAnalyzer().run(doc, rg, kg)
    return container.children


class TestAlgorithmDetection:
    def test_basic_algorithm(self):
        result = _run([_make_para("Algorithm 1: Bubble Sort")])
        assert len(result) == 1
        assert isinstance(result[0], AlgorithmBlock)
        assert result[0].algorithm_name == "Bubble Sort"
        assert result[0].algorithm_number == "1"

    def test_russian_prefix(self):
        result = _run([_make_para("Алгоритм 2. Быстрая сортировка")])
        assert isinstance(result[0], AlgorithmBlock)
        assert result[0].algorithm_number == "2"

    def test_dotted_number(self):
        result = _run([_make_para("Algorithm 3.1: Matrix multiply")])
        assert isinstance(result[0], AlgorithmBlock)
        assert result[0].algorithm_number == "3.1"

    def test_no_name(self):
        result = _run([_make_para("Algorithm 5:")])
        assert isinstance(result[0], AlgorithmBlock)
        assert result[0].algorithm_number == "5"

    def test_not_algorithm(self):
        result = _run([_make_para("This is a normal paragraph.")])
        assert isinstance(result[0], ParagraphBlock)

    def test_id_preserved(self):
        p = _make_para("Algorithm 1: Test")
        original_id = p.id
        result = _run([p])
        assert result[0].id == original_id

    def test_mixed_children(self):
        result = _run([
            _make_para("Normal text"),
            _make_para("Algorithm 1: Sort"),
            _make_para("More text"),
        ])
        types = [type(r).__name__ for r in result]
        assert types == ["ParagraphBlock", "AlgorithmBlock", "ParagraphBlock"]

    def test_tombstoned_skipped(self):
        p = _make_para("Algorithm 1: Test")
        p.is_tombstoned = True
        result = _run([p])
        assert isinstance(result[0], ParagraphBlock)
