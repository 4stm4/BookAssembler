"""E2E: a table of a scanned book page read by the whole pipeline - what it
is made of, and where the page-aware build sets it.

The fixture is a page cut out of a scanned book (the Intel Series 3000
Reference Manual's 3003 page, tests/fixtures/figure): a pin table with no
rules between its rows, its cells of one to three lines, a head of two
lines - beside a logic diagram, over the logic equations set line upon
line between rules. Its table was read off the printed page by eye: its
heads, and what stands in each column under them.

The page goes through the whole pipeline (PdfSourceAdapter, every
analyzer) and the page-aware build. The test asks that

- the page's tables are the one: the equations under it are lines of
  text, no table of one column;
- its columns are the printed ones, under their heads - a head of two
  lines one head - and each column holds what the print sets in it;
- the rebuild keeps the page a page, and sets the table where it printed:
  its words as far from the heading over it, across and down, as on the
  source page (_PLACE_PT).

How heavy its type is drawn is not asked here: the print's is a bold the
builder does not match yet, and the table's ink laid over the print's
misses more than a figure's may.
"""

import re
from pathlib import Path

import pytest

from src.krm.models import KnowledgeDocument, TableBlock
from tests.e2e.test_figure_overlay import _line_rect
from tests.e2e.test_paragraph_overlay import _build_pdf, _extract

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "figure" / "intel3000_2-32.pdf"

# The table's heads, left to right.
HEADS = ["PIN", "SYMBOL", "NAME AND FUNCTION", "TYPE"]
# What the print sets under each head, as OCR reads it surely (its
# subscripts and its "Vcc" it does not).
COLUMNS = [
    ["1,7,8,11", "18,21,23", "27", "2,5,6,10", "19,20,24", "26", "17", "4,9,12", "13,15,16", "3", "28", "14"],
    ["GND"],
    ["Standard carry", "look-ahead", "inputs", "Carry input", "Carry outputs", "output enable", "volt supply",
     "Ground"],
    ["Active", "HIGH", "LOW"],
]
# The heading over the table, and words of it the rebuild is measured by.
HEADING = "PIN DESCRIPTION"
PLACED = ["SYMBOL", "Standard carry", "Carry input", "output enable", "volt supply", "Ground"]
# How far off its printed place against the heading a word may stand (pt).
_PLACE_PT = 2.0


def _tables(doc: KnowledgeDocument) -> list:
    out = []

    def walk(node):
        for child in getattr(node, "children", None) or []:
            if isinstance(child, TableBlock) and not child.is_tombstoned:
                out.append(child)
            walk(child)

    for root in doc.root_containers:
        walk(root)
    return out


def _text(cell) -> str:
    return " ".join(sp.text for unit in cell.content for il in unit.inlines for sp in il.spans)


def _letters(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def _x0(cell) -> float:
    return cell.visual_layout.bounding_box.x0


@pytest.fixture(scope="module")
def page():
    return _extract(FIXTURE)


def test_the_page_s_tables_are_the_pin_table_alone(page):
    tables = _tables(page)
    assert len(tables) == 1, [[_text(c) for c in t.grid[0]] for t in tables]


def test_its_columns_are_the_printed_ones(page):
    [table] = _tables(page)
    heads = sorted(table.grid[0], key=_x0)
    assert [_letters(_text(c)) for c in heads] == [_letters(h) for h in HEADS]

    # each cell under the head it stands nearest across
    held = [[] for _ in heads]
    for row in table.grid[1:]:
        for cell in row:
            column = min(range(len(heads)), key=lambda k: abs(_x0(heads[k]) - _x0(cell)))
            held[column].append(_letters(_text(cell)))
    missing = [(HEADS[k], text) for k, texts in enumerate(COLUMNS) for text in texts
               if not any(_letters(text) in cell for cell in held[k])]
    assert not missing, f"not under their heads: {missing}; the columns hold {held}"


def test_the_table_is_rebuilt_where_it_printed(page, tmp_path):
    fitz = pytest.importorskip("pymupdf")
    pdf_path = Path(_build_pdf(page, str(tmp_path), "table_page_doc"))
    assert len(fitz.open(pdf_path)) == 1, "the page ran onto another"

    _, src_head = _line_rect(fitz, FIXTURE, HEADING)
    out_page, out_head = _line_rect(fitz, pdf_path, HEADING)
    assert src_head is not None and out_head is not None, f"{HEADING!r} not found"
    off = []
    for words in PLACED:
        _, src = _line_rect(fitz, FIXTURE, words)
        at, out = _line_rect(fitz, pdf_path, words)
        assert src is not None and out is not None and at == out_page, f"{words!r} not found"
        dx = (out.x0 - out_head.x0) - (src.x0 - src_head.x0)
        dy = (out.y1 - out_head.y1) - (src.y1 - src_head.y1)
        if max(abs(dx), abs(dy)) > _PLACE_PT:
            off.append(f"{words!r}: {dx:+.1f}pt across, {dy:+.1f}pt down")
    assert not off, f"off their printed places against {HEADING!r} - " + "; ".join(off)
