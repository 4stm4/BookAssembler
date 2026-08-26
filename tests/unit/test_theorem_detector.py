"""Unit tests for TheoremDetectorAnalyzer and semantic decorator wire-up."""

import pytest

from src.analyzers.theorem_detector import TheoremDetectorAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    ExampleSpec,
    KnowledgeDocument,
    ParagraphBlock,
    ProofSpec,
    RemarkSpec,
    StyledTextSpan,
    TextLineInline,
    TheoremSpec,
)


def _make_doc(*texts: str) -> KnowledgeDocument:
    children = []
    for t in texts:
        p = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=t)])])
        children.append(p)
    doc = KnowledgeDocument(
        root_containers=[ContainerUnit(title="ch1", level=1, children=children)]
    )
    return doc


def _run(doc: KnowledgeDocument) -> KnowledgeDocument:
    analyzer = TheoremDetectorAnalyzer()
    analyzer.run(doc, ReadingGraph(), KnowledgeGraph(), {})
    return doc


class TestTheoremDetection:
    def test_basic_theorem(self):
        doc = _run(_make_doc("Theorem 1. Every group has an identity element."))
        assert len(doc.semantic_units) == 1
        spec = doc.semantic_units[0]
        assert isinstance(spec, TheoremSpec)
        assert spec.statement_type == "theorem"
        assert spec.number == "1"

    def test_lemma_ru(self):
        doc = _run(_make_doc("Лемма 3.2: Для любого x верно неравенство."))
        assert len(doc.semantic_units) == 1
        spec = doc.semantic_units[0]
        assert isinstance(spec, TheoremSpec)
        assert spec.statement_type == "lemma"
        assert spec.number == "3.2"

    def test_theorem_with_name(self):
        doc = _run(_make_doc("Theorem 2 (Cauchy). The integral vanishes."))
        assert len(doc.semantic_units) == 1
        spec = doc.semantic_units[0]
        assert spec.name == "Cauchy"
        assert spec.number == "2"

    def test_corollary(self):
        doc = _run(_make_doc("Corollary 5. Follows immediately."))
        spec = doc.semantic_units[0]
        assert isinstance(spec, TheoremSpec)
        assert spec.statement_type == "corollary"

    def test_proposition_ru(self):
        doc = _run(_make_doc("Утверждение 1 — Значения ограничены."))
        spec = doc.semantic_units[0]
        assert spec.statement_type == "proposition"


class TestProofDetection:
    def test_proof_after_theorem(self):
        doc = _run(_make_doc(
            "Theorem 1. Statement.",
            "Proof. We proceed by induction.",
        ))
        assert len(doc.semantic_units) == 2
        theorem = doc.semantic_units[0]
        proof = doc.semantic_units[1]
        assert isinstance(proof, ProofSpec)
        assert proof.proved_statement_id == theorem.target_block_id

    def test_proof_ru(self):
        doc = _run(_make_doc("Доказательство: Очевидно."))
        spec = doc.semantic_units[0]
        assert isinstance(spec, ProofSpec)


class TestExampleDetection:
    def test_example_numbered(self):
        doc = _run(_make_doc("Example 3.1. Consider the function f(x) = x^2."))
        spec = doc.semantic_units[0]
        assert isinstance(spec, ExampleSpec)
        assert spec.number == "3.1"

    def test_example_ru(self):
        doc = _run(_make_doc("Пример 2 — Рассмотрим случай n=1."))
        spec = doc.semantic_units[0]
        assert isinstance(spec, ExampleSpec)
        assert spec.number == "2"


class TestRemarkDetection:
    def test_remark(self):
        doc = _run(_make_doc("Remark 1. This is worth noting."))
        spec = doc.semantic_units[0]
        assert isinstance(spec, RemarkSpec)
        assert spec.number == "1"

    def test_remark_ru(self):
        doc = _run(_make_doc("Замечание. Обратите внимание на границу."))
        spec = doc.semantic_units[0]
        assert isinstance(spec, RemarkSpec)


class TestNoFalsePositives:
    def test_plain_paragraph(self):
        doc = _run(_make_doc("This is a regular paragraph."))
        assert len(doc.semantic_units) == 0

    def test_theorem_in_middle_of_text(self):
        doc = _run(_make_doc("According to the theorem above, we can derive."))
        assert len(doc.semantic_units) == 0


class TestMetadataDecorator:
    def test_metadata_set(self):
        doc = _run(_make_doc("Theorem 1. Statement."))
        para = doc.root_containers[0].children[0]
        assert para.metadata["semantic_decorator"] == "theorem"
        assert para.metadata["statement_type"] == "theorem"
        assert para.metadata["theorem_number"] == "1"

    def test_semantic_units_on_doc(self):
        doc = _run(_make_doc("Lemma 1. X.", "Proof: Y."))
        assert len(doc.semantic_units) == 2
