"""Unit tests for TheoremDetectorAnalyzer and semantic decorator wire-up."""

import pytest

from src.analyzers.theorem import TheoremDetectorAnalyzer
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


class TestCrossBlockContext:
    def test_theorem_body_marked(self):
        doc = _run(_make_doc(
            "Theorem 1. Let G be a group.",
            "Then G has an identity element.",
            "This follows from the axioms.",
            "Example 1. Consider Z.",
        ))
        children = doc.root_containers[0].children
        assert children[0].metadata["semantic_decorator"] == "theorem"
        assert children[1].metadata["semantic_decorator"] == "theorem_body"
        assert children[1].metadata["belongs_to"] == children[0].id
        assert children[2].metadata["semantic_decorator"] == "theorem_body"
        assert children[3].metadata["semantic_decorator"] == "example"

    def test_proof_body_and_end_marker(self):
        doc = _run(_make_doc(
            "Theorem 1. Statement.",
            "Proof. We show that...",
            "By induction on n...",
            "□",
            "Regular paragraph after proof.",
        ))
        children = doc.root_containers[0].children
        assert children[1].metadata["semantic_decorator"] == "proof"
        assert children[2].metadata["semantic_decorator"] == "proof_body"
        assert children[3].metadata["semantic_decorator"] == "proof_body"
        assert children[3].metadata.get("proof_end") is True
        assert "semantic_decorator" not in (children[4].metadata or {})

    def test_proof_links_to_theorem(self):
        doc = _run(_make_doc(
            "Theorem 2.1. Important result.",
            "Proof. Straightforward.",
        ))
        proof_spec = [s for s in doc.semantic_units if isinstance(s, ProofSpec)][0]
        theorem_id = doc.root_containers[0].children[0].id
        assert proof_spec.proved_statement_id == theorem_id

    def test_remark_body_continuation(self):
        doc = _run(_make_doc(
            "Remark 1. Note that...",
            "This is worth emphasizing.",
            "Theorem 2. Next result.",
        ))
        children = doc.root_containers[0].children
        assert children[0].metadata["semantic_decorator"] == "remark"
        assert children[1].metadata["semantic_decorator"] == "remark_body"
        assert children[2].metadata["semantic_decorator"] == "theorem"

    def test_non_paragraph_breaks_context(self):
        doc = _make_doc("Theorem 1. Statement.")
        container = doc.root_containers[0]
        sub = ContainerUnit(title="Section", level=2, children=[])
        container.children.append(sub)
        p = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="After section.")])])
        container.children.append(p)
        _run(doc)
        assert "semantic_decorator" not in (p.metadata or {})
