"""A scanned page read in columns is rebuilt where it printed
(page_assembler._reads_in_columns, _render_printed_page); a narrow column
of prose is no single-column table (table.rules._carried_on)."""

from src.analyzers.table.rules import _carried_on
from src.assembler.page_assembler import PageSlot, _reads_in_columns, _render_printed_page
from src.krm.models import (
    ContainerUnit,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TableBlock,
    TextLineInline,
    VisualLayout,
)


def _printed(text: str, x0: float, y0: float, x1: float, y1: float) -> ParagraphBlock:
    """A scanned page's paragraph of one line, its print read."""
    block = ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(page_or_screen_index=0,
                                   bounding_box=NormalizedRect(x0=x0, y0=y0, x1=x1, y1=y1)),
    )
    block.metadata["printed_lines"] = [{
        "part": "line", "text": text, "page": 0, "box": [x0, y0, x1, y1], "baseline": y1,
        "skew": 0.0, "words": [], "area": 0.0, "cap": 0.7, "size": 7.5, "face": "sans",
        "bold": False, "italic": False, "rgb": None, "underline": None, "overlines": [],
        "page_pt": [612.0, 792.0],
    }]
    return block


def test_a_page_of_columns_side_by_side_reads_in_columns():
    left = _printed("The CPE provides the arithmetic, logic", 0.06, 0.11, 0.31, 0.12)
    right = _printed("ALS and is also available via a three", 0.34, 0.11, 0.58, 0.12)
    assert _reads_in_columns(PageSlot(page_index=0, blocks=[ContainerUnit(title="Book"), left, right]))


def test_a_page_of_one_column_does_not():
    one = _printed("It should be noted that state T4 of M1", 0.09, 0.41, 0.86, 0.42)
    two = _printed("A few instructions require an extra state", 0.09, 0.47, 0.86, 0.48)
    assert not _reads_in_columns(PageSlot(page_index=0, blocks=[one, two]))


def test_a_page_with_a_block_not_set_as_printed_does_not():
    left = _printed("The CPE provides the arithmetic, logic", 0.06, 0.11, 0.31, 0.12)
    right = _printed("ALS and is also available via a three", 0.34, 0.11, 0.58, 0.12)
    assert not _reads_in_columns(PageSlot(page_index=0, blocks=[left, right, TableBlock()]))


def test_its_columns_stand_side_by_side_in_one_picture():
    left = _printed("The CPE provides the arithmetic, logic", 0.06, 0.11, 0.31, 0.12)
    right = _printed("ALS and is also available via a three", 0.34, 0.11, 0.58, 0.12)
    out = _render_printed_page(PageSlot(page_index=0, blocks=[left, right]))
    assert out.count("\\begin{tikzpicture}") == 1
    assert "\\scalebox" in out


def test_a_narrow_column_of_prose_is_no_table():
    lines = ["The A LS is capable of a variety of", "arithmetic and logic operations, in-",
             "cluding 2's complement addition, in-", "crementing, and decrementing, plus",
             "logical AND, inclusive-OR, exclusive-", "NOR, and logical complement. The"]
    assert _carried_on(lines)


def test_a_list_of_entries_is_no_prose():
    assert not _carried_on(["Standard carry", "Carry input", "Carry outputs", "Ground", "Supply"])
