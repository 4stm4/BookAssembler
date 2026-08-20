"""Unit tests for ListDetectorAnalyzer (KRM_ENTITIES_MAP P0.1)."""

from typing import List

from src.analyzers.list_detector import ListDetectorAnalyzer, _classify_marker
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _para(text: str) -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])]
    )


def _doc(children: List) -> KnowledgeDocument:
    root = ContainerUnit(title="root", level=1, children=list(children))
    return KnowledgeDocument(title="t", source_uri="test://", root_containers=[root])


def test_classify_marker_all_styles() -> None:
    assert _classify_marker("• foo")[0] == "bullet"
    assert _classify_marker("- foo")[0] == "bullet"
    assert _classify_marker("* foo")[0] == "bullet"
    assert _classify_marker("1. foo")[0] == "ordered"
    assert _classify_marker("12) foo")[0] == "ordered"
    assert _classify_marker("a) foo")[0] == "alpha"
    assert _classify_marker("а) фу")[0] == "alpha"  # cyrillic
    assert _classify_marker("iv. foo")[0] == "roman"
    assert _classify_marker("no marker here") is None


def test_group_bullets_into_listblock() -> None:
    doc = _doc([_para("• first"), _para("• second"), _para("• third")])
    ListDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

    root = doc.root_containers[0]
    assert len(root.children) == 1
    lst = root.children[0]
    assert isinstance(lst, ListBlock)
    assert lst.list_style == "bullet"
    assert len(lst.items) == 3
    assert all(isinstance(it, ListItemBlock) for it in lst.items)
    # marker stripped from item text
    first_para = lst.items[0].content[0]
    assert isinstance(first_para, ParagraphBlock)
    assert first_para.inlines[0].spans[0].text == "first"
    # marker preserved on ListItemBlock
    assert lst.items[0].marker == "•"


def test_single_item_not_promoted() -> None:
    """One dashed line is prose, not a list."""
    doc = _doc([_para("- lonely"), _para("normal paragraph")])
    ListDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    root = doc.root_containers[0]
    assert len(root.children) == 2
    assert all(isinstance(c, ParagraphBlock) for c in root.children)


def test_ordered_and_bullet_are_separate_groups() -> None:
    doc = _doc([
        _para("1. one"), _para("2. two"),
        _para("normal"),
        _para("• bullet1"), _para("• bullet2"),
    ])
    ListDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    root = doc.root_containers[0]
    assert len(root.children) == 3
    ordered, prose, bullet = root.children
    assert isinstance(ordered, ListBlock) and ordered.list_style == "ordered"
    assert isinstance(prose, ParagraphBlock)
    assert isinstance(bullet, ListBlock) and bullet.list_style == "bullet"


def test_paragraph_between_items_splits_lists() -> None:
    doc = _doc([_para("• a"), _para("• b"), _para("interrupt"), _para("• c"), _para("• d")])
    ListDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    root = doc.root_containers[0]
    assert len(root.children) == 3
    assert isinstance(root.children[0], ListBlock)
    assert isinstance(root.children[1], ParagraphBlock)
    assert isinstance(root.children[2], ListBlock)


def test_nested_container_processed() -> None:
    inner = ContainerUnit(title="inner", level=2, children=[
        _para("• x"), _para("• y")
    ])
    doc = KnowledgeDocument(
        title="t", source_uri="test://",
        root_containers=[ContainerUnit(title="root", level=1, children=[inner])],
    )
    ListDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    assert isinstance(inner.children[0], ListBlock)


def test_tombstoned_paragraph_ignored() -> None:
    p1 = _para("• a"); p2 = _para("• b")
    tomb = _para("• x"); tomb.is_tombstoned = True
    doc = _doc([p1, tomb, p2])
    ListDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    root = doc.root_containers[0]
    # tombstone breaks the run → two singleton items each = no list
    assert not any(isinstance(c, ListBlock) for c in root.children)
