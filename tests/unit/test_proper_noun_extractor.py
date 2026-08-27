"""Unit tests for ProperNounExtractorAnalyzer."""

from src.analyzers.proper_noun_extractor import ProperNounExtractorAnalyzer
from src.graph.knowledge_graph import EntityType, KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _make_doc(*texts: str) -> KnowledgeDocument:
    children = [
        ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=t)])])
        for t in texts
    ]
    return KnowledgeDocument(
        root_containers=[ContainerUnit(title="ch1", level=1, children=children)]
    )


def _run(doc):
    kg = KnowledgeGraph()
    ProperNounExtractorAnalyzer().run(doc, ReadingGraph(), kg, {})
    return kg


class TestPersonExtraction:
    def test_initials_surname(self):
        kg = _run(_make_doc("As shown by A. Turing in 1936."))
        persons = [e for e in kg._entities.values() if e.entity_type == EntityType.PERSON]
        assert len(persons) >= 1
        assert any("turing" in p.canonical_name for p in persons)

    def test_two_initials(self):
        kg = _run(_make_doc("Work by D.E. Knuth is foundational."))
        persons = [e for e in kg._entities.values() if e.entity_type == EntityType.PERSON]
        assert len(persons) >= 1

    def test_full_name(self):
        kg = _run(_make_doc("Dennis Ritchie created C."))
        persons = [e for e in kg._entities.values() if e.entity_type == EntityType.PERSON]
        assert len(persons) >= 1


class TestProductExtraction:
    def test_pdp11(self):
        kg = _run(_make_doc("The PDP-11 was a 16-bit minicomputer."))
        products = [e for e in kg._entities.values() if e.entity_type == EntityType.PRODUCT]
        assert len(products) == 1
        assert "pdp-11" in products[0].canonical_name

    def test_mc68000(self):
        kg = _run(_make_doc("The MC68000 processor was introduced in 1979."))
        products = [e for e in kg._entities.values() if e.entity_type == EntityType.PRODUCT]
        assert len(products) >= 1


class TestDateExtraction:
    def test_month_year(self):
        kg = _run(_make_doc("Published in January 2020."))
        dates = [e for e in kg._entities.values() if e.entity_type == EntityType.DATE]
        assert len(dates) == 1

    def test_dot_date(self):
        kg = _run(_make_doc("Дата публикации: 15.03.2021."))
        dates = [e for e in kg._entities.values() if e.entity_type == EntityType.DATE]
        assert len(dates) == 1


class TestVersionExtraction:
    def test_version(self):
        kg = _run(_make_doc("Updated in v2.3.1 of the specification."))
        versions = [e for e in kg._entities.values() if e.entity_type == EntityType.VERSION]
        assert len(versions) == 1


class TestDeduplication:
    def test_same_entity_once(self):
        kg = _run(_make_doc(
            "The PDP-11 was popular.",
            "The PDP-11 ran UNIX.",
        ))
        products = [e for e in kg._entities.values() if e.entity_type == EntityType.PRODUCT]
        assert len(products) == 1
        edges = [e for e in kg._edges if e.relation_type == RelationType.MENTIONS_ENTITY]
        assert len(edges) == 2


class TestEdges:
    def test_mentions_entity_edge(self):
        doc = _make_doc("The PDP-11 was designed by DEC.")
        kg = _run(doc)
        para = doc.root_containers[0].children[0]
        edges = kg.get_outgoing_edges(para.id, RelationType.MENTIONS_ENTITY)
        assert len(edges) >= 1
