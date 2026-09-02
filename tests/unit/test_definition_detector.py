"""Unit tests for DefinitionDetectorAnalyzer."""

import pytest

from src.analyzers.definition import DefinitionDetectorAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    DefinitionSpec,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _make_doc(*texts: str) -> KnowledgeDocument:
    children = []
    for t in texts:
        p = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=t)])])
        children.append(p)
    return KnowledgeDocument(
        root_containers=[ContainerUnit(title="ch1", level=1, children=children)]
    )


def _run(doc: KnowledgeDocument) -> KnowledgeDocument:
    analyzer = DefinitionDetectorAnalyzer()
    analyzer.run(doc, ReadingGraph(), KnowledgeGraph(), {})
    return doc


class TestDefinitionPrefix:
    def test_definition_en(self):
        doc = _run(_make_doc("Definition 1. A group is a set with a binary operation."))
        assert len(doc.semantic_units) == 1
        spec = doc.semantic_units[0]
        assert isinstance(spec, DefinitionSpec)

    def test_definition_ru(self):
        doc = _run(_make_doc("Определение 3.1: Множество — это совокупность объектов."))
        spec = doc.semantic_units[0]
        assert isinstance(spec, DefinitionSpec)
        assert spec.term == "Множество"
        assert "совокупность" in spec.definition_text


class TestDefinitionPattern:
    def test_is_defined_as(self):
        doc = _run(_make_doc("A manifold is defined as a topological space that locally resembles Euclidean space."))
        spec = doc.semantic_units[0]
        assert isinstance(spec, DefinitionSpec)
        assert spec.term == "A manifold"
        assert "topological" in spec.definition_text

    def test_dash_eto(self):
        doc = _run(_make_doc("Алгоритм — это конечная последовательность шагов."))
        spec = doc.semantic_units[0]
        assert spec.term == "Алгоритм"
        assert "последовательность" in spec.definition_text

    def test_is_called(self):
        doc = _run(_make_doc("A matrix is called symmetric if A equals A transpose."))
        spec = doc.semantic_units[0]
        assert spec.term == "A matrix"

    def test_means(self):
        doc = _run(_make_doc("Convergence means the sequence approaches a limit."))
        spec = doc.semantic_units[0]
        assert spec.term == "Convergence"


class TestNoFalsePositives:
    def test_plain_paragraph(self):
        doc = _run(_make_doc("Regular text without any definition patterns."))
        assert len(doc.semantic_units) == 0

    def test_already_decorated_skipped(self):
        doc = _make_doc("Definition 1. A group is a set.")
        para = doc.root_containers[0].children[0]
        para.metadata = {"semantic_decorator": "theorem"}
        doc = _run(doc)
        assert len(doc.semantic_units) == 0
