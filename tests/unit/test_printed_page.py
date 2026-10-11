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


def test_a_pdf_s_root_container_stands_for_the_document(tmp_path):
    """The PDF adapter's one root container wraps the document - its title
    the document's - and is marked so: no heading is set for it."""
    import pymupdf

    from src.adapters.pdf_adapter import PdfSourceAdapter
    from src.krm.models import DOCUMENT_CONTAINER

    path = tmp_path / "a_page.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Some text on a page.")
    pdf.save(path)
    with open(path, "rb") as fh:
        doc = PdfSourceAdapter().parse(fh, f"file://{path}")
    assert doc.root_containers[0].semantic_type == DOCUMENT_CONTAINER


# --- a table of a scanned page, hung where it printed ----------------------

import pytest

from src.assembler.latex_builder import _printed_extent, _printed_table, _table_node, _table_place
from src.krm.models import ParagraphBlock as _Paragraph, StyleDescriptor, TableCell

_PAGE_PT = (400.0, 600.0)   # the page the table was read off, pt


def _cell(text: str, x0: float, y0: float) -> TableCell:
    return TableCell(
        content=[_Paragraph(inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=x0, y0=y0, x1=x0 + 0.06, y1=y0 + 0.012),
            page_or_screen_index=0, style=StyleDescriptor(font_size_pt=7.0),
        ),
    )


def _table(rules=(0.29, 0.315), page_pt=_PAGE_PT, **marks) -> TableBlock:
    """A table of two rows on the left of its page, a rule over it and one
    under its heads."""
    grid = [[_cell("PIN", 0.10, 0.30), _cell("SYMBOL", 0.20, 0.30), _cell("TYPE", 0.32, 0.30)],
            [_cell("17", 0.10, 0.32), _cell("Cn", 0.20, 0.32), _cell("Active", 0.32, 0.32)]]
    table = TableBlock(
        grid=grid, row_count=2, column_count=3,
        visual_layout=VisualLayout(page_or_screen_index=0,
                                   bounding_box=NormalizedRect(x0=0.10, y0=0.30, x1=0.38, y1=0.332)),
    )
    table.metadata.update({"rule_y": list(rules), **marks})
    if page_pt:
        table.metadata["page_pt"] = list(page_pt)
    return table


def test_a_table_with_a_rule_over_it_has_a_place_on_its_page():
    x0, top, x1, bottom = _table_place(_table())
    mm = 25.4 / 72.0
    assert (x0, x1) == pytest.approx((0.10 * 400 * mm, 0.38 * 400 * mm))
    # from its top rule down to its last line - or the rule under it
    assert (top, bottom) == pytest.approx((0.29 * 600 * mm, 0.332 * 600 * mm))
    assert _printed_extent(_table()) == _table_place(_table())


def test_a_table_the_builder_cannot_hang_has_none():
    assert _table_place(_table(page_pt=None)) is None            # read off no page
    assert _table_place(_table(rules=(0.315,))) is None          # no rule over its first row
    assert _table_place(_table(box_grid=True)) is None           # drawn as boxes
    assert _table_place(_table(label_table=True)) is None        # labels and their values


def test_a_table_is_hung_by_its_top_rule_and_its_first_column():
    node = _table_node(_table(), origin=(0.0, 0.0))
    assert "\\begin{tabular}" in node and "\\begin{center}" not in node
    import re
    x, y = map(float, re.search(r"at \(([-0-9.]+)mm, ([-0-9.]+)mm\)", node).groups())
    mm = 25.4 / 72.0
    # its top rule's upper edge, down the page
    assert -y == pytest.approx(0.29 * 600 * mm, abs=0.3)
    # a column's lead before its first column's text
    assert 0.10 * 400 * mm - 3.0 < x < 0.10 * 400 * mm


def test_a_table_in_the_flow_stands_as_far_in_as_it_printed():
    out = _printed_table(_table(), column_left=0.05 * 400 * 25.4 / 72.0)
    assert out.count("\\begin{tikzpicture}") == 1 and "\\begin{center}" not in out
    import re
    x = float(re.search(r"at \(([-0-9.]+)mm,", out).group(1))
    # 5% of the page in from its column's edge, less its column's lead
    assert 0.0 < x <= 0.05 * 400 * 25.4 / 72.0


def test_a_page_with_a_table_beside_its_text_is_rebuilt_where_it_printed():
    beside = _printed("LOGIC DIAGRAM of the look-ahead carry", 0.50, 0.30, 0.90, 0.31)
    slot = PageSlot(page_index=0, blocks=[_table(page_pt=(612.0, 792.0)), beside])   # the page _printed reads off
    assert _reads_in_columns(slot)
    out = _render_printed_page(slot)
    assert out.count("\\begin{tikzpicture}") == 1
    assert "\\begin{tabular}" in out and "\\begin{center}" not in out
