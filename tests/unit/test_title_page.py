"""TitlePageAnalyzer — detects blank/cover pages and merges front matter.

The case that matters here: a paragraph an earlier analyzer already
tombstoned (a repeating running header EphemeraDetector removed, present
even on page 0) must not be reclassified into a fresh BlankPageBlock/
TitlePageBlock at the same id — that resurrects the node and trips the
No Silent Deletions guard (RFC 0001 §2.4). This actually failed a real
pipeline run on the Intel 3000 reference manual ("Analyzer
'TitlePageAnalyzer' un-tombstoned node ...").
"""

import pytest

from src.analyzers.title_page import TitlePageAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    BlankPageBlock,
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    TitlePageBlock,
    VisualLayout,
)


def _para(text: str, page: int) -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.1, 0.1, 0.9, 0.2),
            page_or_screen_index=page,
        ),
    )


def _run(children, page_count=20):
    root = ContainerUnit(title="root", level=1, children=children)
    doc = KnowledgeDocument(title="t", source_uri="test://",
                            metadata={"page_count": page_count},
                            root_containers=[root])
    TitlePageAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    return root


class TestBlankIsAPropertyOfThePage:
    """MetaPost: the page number "2" at the foot of a page of text was
    relabelled BlankPageBlock and its text discarded — every folio of the
    book went that way, and with it where the contents entries point."""

    def test_a_page_number_on_a_page_of_text_keeps_its_text(self):
        body = _para("MetaPost — это язык программирования, очень похожий на METAFONT.", page=2)
        folio = _para("2", page=2)
        root = _run([body, folio])
        kept = next(c for c in root.children if c.id == folio.id)
        assert type(kept) is ParagraphBlock
        assert kept.inlines[0].spans[0].text == "2"

    def test_a_page_holding_only_a_number_is_still_blank(self):
        folio = _para("7", page=7)
        root = _run([_para("Text on another page.", page=6), folio])
        assert isinstance(next(c for c in root.children if c.id == folio.id), BlankPageBlock)


class TestBlankPageTombstoneIsRespected:
    def test_a_tombstoned_near_empty_block_is_not_replaced(self):
        """The bug: replacing it resurrects the node at the same id."""
        ghost = _para("x", page=1)
        ghost.is_tombstoned = True
        root = _run([ghost])
        survivor = next(c for c in root.children if c.id == ghost.id)
        assert isinstance(survivor, ParagraphBlock)
        assert not isinstance(survivor, BlankPageBlock)
        assert survivor.is_tombstoned

    def test_a_tombstoned_page_zero_block_is_not_made_a_cover(self):
        ghost = _para("", page=0)
        ghost.is_tombstoned = True
        root = _run([ghost])
        survivor = next(c for c in root.children if c.id == ghost.id)
        assert not isinstance(survivor, TitlePageBlock)
        assert survivor.is_tombstoned

    def test_an_ordinary_near_empty_block_still_becomes_blank(self):
        root = _run([_para("", page=1)])
        assert isinstance(root.children[0], BlankPageBlock)

    def test_an_ordinary_page_zero_block_still_becomes_a_cover(self):
        root = _run([_para("", page=0)])
        assert isinstance(root.children[0], TitlePageBlock)
        assert root.children[0].page_role == "cover"


class TestTitlePageDetectionExcludesTombstonedText:
    def test_a_tombstoned_running_header_does_not_join_the_title_page(self):
        header = _para("RUNNING HEADER RUNNING HEADER", page=0)
        header.is_tombstoned = True
        root = _run([
            header,
            _para("A GREAT BOOK", page=0),
            _para("Copyright (c) 2020 Some Publisher", page=0),
            _para("ISBN 978-0-000-00000-0", page=0),
        ])
        titles = [c for c in root.children if isinstance(c, TitlePageBlock)]
        assert titles, "a real title page should still be detected"
        joined = " ".join(ln.spans[0].text for ln in titles[0].inlines)
        assert "RUNNING HEADER" not in joined
