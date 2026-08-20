"""Unit tests for TocEntryBlock + BlockClassifier TOC parsing (P0.2)."""

from typing import List

from src.analyzers.block_classifier import BlockClassifierAnalyzer, _parse_toc_entry
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    TocEntryBlock,
    VisualLayout,
)


def _para_at(text: str, page: int) -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
            page_or_screen_index=page,
        ),
    )


def test_parse_toc_entry_hierarchical() -> None:
    text, num, page = _parse_toc_entry("1.2  Registers .......... 45")
    assert num == "1.2"
    assert page == 44  # 0-based
    assert "Registers" in text


def test_parse_toc_entry_word_prefix() -> None:
    text, num, page = _parse_toc_entry("Глава 5   Прерывания        102")
    assert num == "Глава 5"
    assert page == 101


def test_parse_toc_entry_no_page() -> None:
    text, num, page = _parse_toc_entry("2. Introduction to KRM")
    assert num == "2."
    assert page is None


def test_toc_run_creates_typed_entries() -> None:
    """A run of TOC-like ParagraphBlocks becomes TocEntryBlocks in a toc container."""
    root = ContainerUnit(title="root", level=1, children=[
        _para_at("Introduction  1", 1),
        _para_at("1.1  Registers  5", 1),
        _para_at("1.2  Memory  10", 1),
        _para_at("2.  Instruction Set  15", 1),
        _para_at("3.  Interrupts  25", 1),
    ])
    doc = KnowledgeDocument(
        title="t", source_uri="test://",
        metadata={"page_count": 100},
        root_containers=[root],
    )
    BlockClassifierAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

    tocs = [c for c in root.children if isinstance(c, ContainerUnit) and c.semantic_type == "toc"]
    assert len(tocs) == 1
    toc = tocs[0]
    entries = [e for e in toc.children if isinstance(e, TocEntryBlock)]
    assert len(entries) == 5
    # 1.1 line → chapter_number="1.1", target_page=4 (0-based)
    r = next(e for e in entries if e.chapter_number == "1.1")
    assert r.target_page == 4
    assert "Registers" in r.entry_text


def test_toc_anchor_link_matches_headings() -> None:
    """TocEntryBlock.anchor_id is populated when chapter_number matches a heading."""
    ch1 = ContainerUnit(title="1.  Introduction", level=1, children=[
        _para_at("body", 0),
    ])
    ch2 = ContainerUnit(title="2.  Registers", level=1, children=[
        _para_at("body", 5),
    ])
    # TOC container built manually; classifier will still run the anchor pass.
    toc_container = ContainerUnit(
        title="Оглавление", level=1, semantic_type="toc",
        children=[
            TocEntryBlock(entry_text="Introduction", chapter_number="1.", target_page=0),
            TocEntryBlock(entry_text="Registers", chapter_number="2.", target_page=5),
        ],
    )
    doc = KnowledgeDocument(
        title="t", source_uri="test://",
        metadata={"page_count": 100},
        root_containers=[ch1, ch2, toc_container],
    )
    BlockClassifierAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    entries: List[TocEntryBlock] = [e for e in toc_container.children if isinstance(e, TocEntryBlock)]
    ids = {e.chapter_number: e.anchor_id for e in entries}
    assert ids["1."] == ch1.id
    assert ids["2."] == ch2.id
