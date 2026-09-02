"""A running head is defined by repeating (EphemeraDetector).

Ephemera are dropped from the exported document, so promoting a one-off line
near a page edge deletes real content: a page title, a section heading, a table
caption. The rule is repetition across pages, not position alone.
"""
import pytest

from src.analyzers.ephemera_detector import EphemeraDetectorAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    EphemeraBlock,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _para(text, page, y0=0.02, parts=None):
    inlines = [
        TextLineInline(spans=[StyledTextSpan(text=p)])
        for p in (parts or [text])
    ]
    return ParagraphBlock(
        inlines=inlines,
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.1, y0, 0.9, y0 + 0.02),
            page_or_screen_index=page,
        ),
    )


def _run(children):
    c = ContainerUnit(title="ch", children=children)
    doc = KnowledgeDocument(title="T", root_containers=[c])
    EphemeraDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    return c


def _types(c):
    return [type(x).__name__ for x in c.children]


class TestRepetitionRequired:
    def test_repeated_header_is_ephemera(self):
        c = _run([_para("Chapter Three", p) for p in range(4)])
        assert _types(c) == ["EphemeraBlock"] * 4

    def test_one_off_page_title_is_kept(self):
        """Regression: 'CONTENTS' was dropped as a running head."""
        c = _run([
            _para("CONTENTS", 1),
            _para("Introduction", 2, y0=0.30),
        ])
        assert "EphemeraBlock" not in _types(c)

    def test_distinct_table_titles_are_kept(self):
        """Different titles at the same position are not a running head."""
        c = _run([
            _para("Analysis of Computer Use", 4),
            _para("Analysis of Academic Cost", 5),
            _para("TCD Use of UCD Computers", 6),
        ])
        assert _types(c) == ["ParagraphBlock"] * 3

    def test_repeated_footer_is_ephemera(self):
        c = _run([_para("Annual Report", p, y0=0.95) for p in range(3)])
        assert _types(c) == ["EphemeraBlock"] * 3

    def test_page_numbers_stay_positional(self):
        """Page numbers differ by design, so they cannot rely on repetition."""
        c = _run([_para(str(10 + p), p, y0=0.96) for p in range(3)])
        assert _types(c) == ["EphemeraBlock"] * 3

    def test_middle_of_page_is_never_ephemera(self):
        c = _run([_para("Same Line", p, y0=0.45) for p in range(4)])
        assert "EphemeraBlock" not in _types(c)


class TestFullBlockText:
    def test_length_is_judged_on_the_whole_block(self):
        """Blocks hold one inline per source line; the first span is a fragment.

        Judging by the first span alone let long headings pass the <80 test.
        """
        long_parts = ["Analysis", "of computer use and the cost of monthly use",
                      "per user category across every department listed"]
        c = _run([_para("", p, parts=long_parts) for p in range(4)])
        assert "EphemeraBlock" not in _types(c)
