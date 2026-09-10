"""TocAnalyzer — detecting the table of contents and typing its entries.

The case that drove this out of BlockClassifier: a "CONTENTS" heading over a
plain section list (the PDP-11 lab report, most old manuals) — no dotted
leaders, no page numbers. The old detector required a trailing page number
and produced nothing, so the editor showed the entries as paragraphs.
"""

from typing import List

from src.analyzers.toc import TocAnalyzer
from src.analyzers.toc.rules import parse_entry, split_merged_entries
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


def _para(text, page: int, lines: List[str] | None = None) -> ParagraphBlock:
    inlines = [
        TextLineInline(spans=[StyledTextSpan(text=t)])
        for t in (lines or [text])
    ]
    return ParagraphBlock(
        inlines=inlines,
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
            page_or_screen_index=page,
        ),
    )


def _run(children, page_count=100):
    root = ContainerUnit(title="root", level=1, children=children)
    doc = KnowledgeDocument(
        title="t", source_uri="test://",
        metadata={"page_count": page_count},
        root_containers=[root],
    )
    TocAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    return root


def _toc_of(root) -> ContainerUnit | None:
    return next(
        (c for c in root.children
         if isinstance(c, ContainerUnit) and c.semantic_type == "toc"),
        None,
    )


# --- parse_entry ----------------------------------------------------------

def test_parse_entry_hierarchical():
    text, num, page = parse_entry("1.2  Registers .......... 45")
    assert num == "1.2" and page == 44 and "Registers" in text


def test_parse_entry_word_prefix():
    text, num, page = parse_entry("Глава 5   Прерывания        102")
    assert num == "Глава 5" and page == 101


def test_parse_entry_no_page():
    text, num, page = parse_entry("2. Introduction to KRM")
    assert num == "2." and page is None


# --- dotted-leader form (the shape the old detector handled) -------------

def test_page_numbered_run_becomes_a_toc():
    root = _run([
        _para("Introduction  1", 1),
        _para("1.1  Registers  5", 1),
        _para("1.2  Memory  10", 1),
        _para("2.  Instruction Set  15", 1),
        _para("3.  Interrupts  25", 1),
    ])
    toc = _toc_of(root)
    assert toc is not None
    entries = [e for e in toc.children if isinstance(e, TocEntryBlock)]
    assert len(entries) == 5
    r = next(e for e in entries if e.chapter_number == "1.1")
    assert r.target_page == 4 and "Registers" in r.entry_text


# --- the new case: heading + section list, no page numbers --------------

def test_contents_heading_over_a_section_list():
    root = _run([
        _para("CONTENTS", 1),
        _para("Section 1 Introduction", 1),
        _para("Section 2 Machine Utilisation", 1),
        _para("Section 3 Application Development", 1),
        _para("Appendix A Equipment", 1),
        _para("Appendix B Staff", 1),
        _para("The report proper begins here with a full sentence of prose.", 2),
    ])
    toc = _toc_of(root)
    assert toc is not None, "a CONTENTS heading over a section list is a TOC"
    entries = [e for e in toc.children if isinstance(e, TocEntryBlock)]
    texts = [e.entry_text for e in entries]
    assert "Section 1 Introduction" in texts
    assert "Appendix B Staff" in texts
    assert not any("full sentence of prose" in t for t in texts)


def test_originals_are_tombstoned_not_deleted():
    root = _run([
        _para("Оглавление", 1),
        _para("Раздел 1 Введение", 1),
        _para("Раздел 2 Архитектура", 1),
        _para("Приложение A Таблицы", 1),
        _para("Приложение B Глоссарий", 1),
    ])
    ghosts = [c for c in root.children
              if isinstance(c, ParagraphBlock) and c.is_tombstoned]
    assert len(ghosts) == 5
    assert all(g.metadata.get("tombstone_reason") == "merged_into_toc"
               for g in ghosts)


# --- merged lines from a column layout ---------------------------------

def test_split_merged_entries():
    merged = ("Section 3 Application Development 3.1 Academic 3.2 Library "
              "Section 4 Central Service")
    parts = split_merged_entries(merged)
    assert parts[0] == "Section 3 Application Development"
    assert "3.1 Academic" in parts
    assert "Section 4 Central Service" in parts


def test_a_block_holding_several_entries_is_split():
    root = _run([
        _para("CONTENTS", 1),
        _para("", 1, lines=[
            "Section 1 Introduction",
            "Section 2 Machine Utilisation 2.1 Computer Activity 2.2 Ancillary",
            "Section 3 Application Development",
            "Appendix A Equipment",
        ]),
    ])
    toc = _toc_of(root)
    assert toc is not None
    texts = [e.entry_text for e in toc.children if isinstance(e, TocEntryBlock)]
    assert "Section 2 Machine Utilisation" in texts
    assert "2.1 Computer Activity" in texts


# --- validation: a short list mid-book is not a TOC --------------------

def test_section_list_in_the_middle_of_the_book_is_not_a_toc():
    root = _run([
        _para("1.1 Something  ", 50),
        _para("1.2 Another  ", 50),
        _para("1.3 More  ", 50),
        _para("1.4 Yet more  ", 50),
    ], page_count=100)
    assert _toc_of(root) is None


def test_anchor_link_matches_headings():
    ch1 = ContainerUnit(title="1.  Introduction", level=1,
                        children=[_para("body", 3)])
    ch2 = ContainerUnit(title="2.  Registers", level=1,
                        children=[_para("body", 8)])
    toc = ContainerUnit(
        title="Оглавление", level=1, semantic_type="toc",
        children=[
            TocEntryBlock(entry_text="Introduction", chapter_number="1.",
                          target_page=2),
            TocEntryBlock(entry_text="Registers", chapter_number="2.",
                          target_page=7),
        ],
    )
    doc = KnowledgeDocument(
        title="t", source_uri="test://", metadata={"page_count": 100},
        root_containers=[ch1, ch2, toc],
    )
    TocAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    ids = {e.chapter_number: e.anchor_id
           for e in toc.children if isinstance(e, TocEntryBlock)}
    assert ids["1."] == ch1.id and ids["2."] == ch2.id
