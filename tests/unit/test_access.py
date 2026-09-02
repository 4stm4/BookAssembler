"""The shared KRM accessors (src/analyzers/access.py).

These replaced private copies in sixteen analyzer packages that had silently
diverged — four implementations of "the block's text", three of "the page",
and two of "the first text", one of which returned the whole block. The cases
below pin the differences that turned out to be deliberate, so a later cleanup
cannot quietly collapse them again.
"""

import pytest

from src.analyzers.access import (
    block_text,
    first_span_text,
    font_size,
    page_of,
    spans,
    style_of,
)
from src.krm.models import (
    NormalizedRect,
    ParagraphBlock,
    StyleDescriptor,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _block(*lines, page=None, size=None):
    block = ParagraphBlock(
        id="b",
        inlines=[TextLineInline(spans=[StyledTextSpan(text=t) for t in line])
                 for line in lines],
    )
    if page is not None or size is not None:
        block.visual_layout = VisualLayout(
            bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
            page_or_screen_index=page or 0,
            style=StyleDescriptor(font_size_pt=size) if size is not None else None,
        )
    return block


class TestBlockText:
    def test_reads_every_inline_not_just_the_first(self):
        """The bug this module exists to prevent: a block holds one inline per
        source line, so the first span is a fragment."""
        b = _block(["Analysis"], ["of", "Algorithms"])
        assert block_text(b) == "Analysis of Algorithms"

    def test_empty_spans_do_not_produce_double_spaces(self):
        b = _block(["A", "", "B"])
        assert block_text(b) == "A B"

    def test_separator_is_a_parameter_for_formulas(self):
        """A formula split across spans must not gain spaces."""
        b = _block(["x", "²", "+1"])
        assert block_text(b, sep="") == "x²+1"

    def test_a_block_with_no_inlines_is_empty_not_an_error(self):
        assert block_text(ParagraphBlock(id="b", inlines=[])) == ""
        assert block_text(ParagraphBlock(id="b", inlines=None)) == ""


class TestFirstSpanText:
    def test_returns_the_opening_fragment_only(self):
        b = _block(["Note:", "the rest"], ["and more"])
        assert first_span_text(b) == "Note:"

    def test_skips_leading_empty_spans(self):
        assert first_span_text(_block(["", "", "Warning"])) == "Warning"

    def test_is_not_the_whole_block(self):
        b = _block(["Theorem", "1.2"])
        assert first_span_text(b) != block_text(b)

    def test_empty_block_gives_empty_string(self):
        assert first_span_text(ParagraphBlock(id="b", inlines=[])) == ""


class TestPageOf:
    def test_reads_the_layout_index(self):
        assert page_of(_block(["x"], page=7)) == 7

    def test_page_zero_is_a_page_not_a_missing_value(self):
        assert page_of(_block(["x"], page=0)) == 0

    def test_no_layout_means_unknown(self):
        assert page_of(ParagraphBlock(id="b", inlines=[])) is None


class TestFontSize:
    def test_reads_the_point_size(self):
        assert font_size(_block(["x"], size=9.5)) == 9.5

    def test_default_is_the_callers_choice(self):
        """footnote wants None for "unknown"; heading wants to assume body text."""
        bare = ParagraphBlock(id="b", inlines=[])
        assert font_size(bare) is None
        assert font_size(bare, default=12.0) == 12.0

    def test_zero_means_absent_not_infinitely_small(self):
        assert font_size(_block(["x"], size=0.0), default=12.0) == 12.0


class TestStyleAndSpans:
    def test_style_is_none_without_layout(self):
        assert style_of(ParagraphBlock(id="b", inlines=[])) is None

    def test_spans_yields_in_reading_order(self):
        b = _block(["a", "b"], ["c"])
        assert [s.text for s in spans(b)] == ["a", "b", "c"]
