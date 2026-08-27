"""Unit tests for CitationLinkerAnalyzer."""

from src.analyzers.citation_linker import CitationLinkerAnalyzer
from src.graph.knowledge_graph import EntityType, KGEntityNode, KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    BibEntryBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _para(text: str) -> ParagraphBlock:
    return ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])])


def _bib(cite_key: str, authors=None, title="", year="") -> BibEntryBlock:
    return BibEntryBlock(
        cite_key=cite_key,
        authors=authors or [],
        title=title,
        year=year,
        raw_text=f"[{cite_key}] {title}",
    )


class TestCitationLinking:
    def test_cite_creates_edge(self):
        bib = _bib("1", title="Some paper")
        para = _para("As shown in [1], the result holds.")
        doc = KnowledgeDocument(
            root_containers=[
                ContainerUnit(title="body", level=1, children=[para]),
                ContainerUnit(title="refs", level=1, children=[bib]),
            ]
        )
        kg = KnowledgeGraph()
        CitationLinkerAnalyzer().run(doc, ReadingGraph(), kg, {})

        cites_edges = [e for e in kg._edges if e.relation_type == RelationType.CITES]
        assert len(cites_edges) == 1
        assert cites_edges[0].source_id == para.id

    def test_multiple_cites(self):
        bib1 = _bib("1", title="Paper A")
        bib2 = _bib("2", title="Paper B")
        para = _para("See [1] and [2] for details.")
        doc = KnowledgeDocument(
            root_containers=[
                ContainerUnit(title="body", level=1, children=[para]),
                ContainerUnit(title="refs", level=1, children=[bib1, bib2]),
            ]
        )
        kg = KnowledgeGraph()
        CitationLinkerAnalyzer().run(doc, ReadingGraph(), kg, {})
        cites_edges = [e for e in kg._edges if e.relation_type == RelationType.CITES]
        assert len(cites_edges) == 2

    def test_unmatched_cite_no_edge(self):
        para = _para("See [99] for details.")
        doc = KnowledgeDocument(
            root_containers=[ContainerUnit(title="body", level=1, children=[para])]
        )
        kg = KnowledgeGraph()
        CitationLinkerAnalyzer().run(doc, ReadingGraph(), kg, {})
        assert len(kg._edges) == 0


class TestAuthoredByLinking:
    def test_author_linked(self):
        bib = _bib("1", authors=["A. Turing"], title="On Computable Numbers")
        para = _para("Some text.")
        doc = KnowledgeDocument(
            root_containers=[
                ContainerUnit(title="body", level=1, children=[para]),
                ContainerUnit(title="refs", level=1, children=[bib]),
            ]
        )
        kg = KnowledgeGraph()
        person = KGEntityNode(
            name="A. Turing",
            entity_type=EntityType.PERSON,
            canonical_name="a. turing",
        )
        kg.add_entity(person)

        CitationLinkerAnalyzer().run(doc, ReadingGraph(), kg, {})
        authored = [e for e in kg._edges if e.relation_type == RelationType.AUTHORED_BY]
        assert len(authored) == 1
        assert authored[0].source_id == person.id


class TestBibEntityCreation:
    def test_bib_entities_created(self):
        bib = _bib("1", title="Important Paper", year="2020")
        doc = KnowledgeDocument(
            root_containers=[ContainerUnit(title="refs", level=1, children=[bib])]
        )
        kg = KnowledgeGraph()
        CitationLinkerAnalyzer().run(doc, ReadingGraph(), kg, {})
        bib_entities = [e for e in kg._entities.values() if e.entity_type == EntityType.BIBLIOGRAPHY_CITE]
        assert len(bib_entities) == 1
        assert bib_entities[0].canonical_name == "1"
