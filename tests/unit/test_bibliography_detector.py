"""Unit tests for BibliographyDetectorAnalyzer (KRM_ENTITIES_MAP P1.6)."""

from typing import List

from src.analyzers.bibliography import (
    BibliographyDetectorAnalyzer,
    _parse_entry,
)
from src.graph.knowledge_graph import KnowledgeGraph
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
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])]
    )


def _doc_with_bib(title: str, entries: List[str]) -> KnowledgeDocument:
    bib = ContainerUnit(
        title=title, level=1,
        children=[_para(t) for t in entries],
    )
    return KnowledgeDocument(
        title="t", source_uri="test://", root_containers=[bib],
    )


def test_parse_entry_numbered() -> None:
    key, authors, year, title, raw = _parse_entry(
        "[3] Knuth, D. E. The Art of Computer Programming. Addison-Wesley, 1997."
    )
    assert key == "3"
    assert year == 1997
    assert authors[0].startswith("Knuth")
    assert "Art of Computer Programming" in title


def test_parse_entry_unnumbered_fabricates_key() -> None:
    key, authors, year, title, raw = _parse_entry(
        "Ritchie, D. M. The Development of the C Language. 1993."
    )
    assert "ritchie" in key
    assert "1993" in key
    assert year == 1993


def test_promote_paragraphs_inside_references_container() -> None:
    doc = _doc_with_bib("References", [
        "[1] Aho, A. V. Compilers. Addison-Wesley, 1986.",
        "[2] Knuth, D. E. TAOCP. Vol 1. Addison-Wesley, 1997.",
        "sh",  # too short — stays as ParagraphBlock
    ])
    BibliographyDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    bib = doc.root_containers[0]
    assert bib.semantic_type == "bibliography"
    entries = [c for c in bib.children if isinstance(c, BibEntryBlock)]
    assert len(entries) == 2
    keys = [e.cite_key for e in entries]
    assert keys == ["1", "2"]


def test_russian_bibliography_title_detected() -> None:
    doc = _doc_with_bib("Список литературы", [
        "1. Кнут Д. Э. Искусство программирования. Т. 1. Вильямс, 1997.",
    ])
    BibliographyDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    bib = doc.root_containers[0]
    assert bib.semantic_type == "bibliography"


def test_non_bibliography_container_untouched() -> None:
    doc = _doc_with_bib("Introduction", [
        "[1] this looks like a bib entry but isn't in a bib container",
    ])
    BibliographyDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    kids = doc.root_containers[0].children
    assert all(isinstance(c, ParagraphBlock) for c in kids)


def test_identity_preserved() -> None:
    p = _para("[1] Aho. Compilers. 1986.")
    original_id = p.id
    doc = KnowledgeDocument(title="t", source_uri="test://",
        root_containers=[ContainerUnit(title="References", level=1, children=[p])])
    BibliographyDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    entry = doc.root_containers[0].children[0]
    assert isinstance(entry, BibEntryBlock)
    assert entry.id == original_id


def test_latex_thebibliography_and_chunker() -> None:
    from src.ai_layer.chunker import _extract_text_from_node, _is_atomic_block
    from src.assembler.latex_builder import build_latex

    doc = _doc_with_bib("References", [
        "[1] Aho, A. V. Compilers. Addison-Wesley, 1986.",
        "[2] Knuth, D. E. TAOCP. Vol 1. Addison-Wesley, 1997.",
    ])
    BibliographyDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

    entry = doc.root_containers[0].children[0]
    assert isinstance(entry, BibEntryBlock)
    assert _is_atomic_block(entry)
    assert "Aho" in _extract_text_from_node(entry)

    tex = build_latex(doc)
    assert "\\begin{thebibliography}" in tex
    assert "\\bibitem{1}" in tex
    assert "\\bibitem{2}" in tex
