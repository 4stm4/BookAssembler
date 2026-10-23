"""E2E: a scanned page of two ruled spec tables, each over its caption -
read by the whole pipeline and set by the page-aware build.

The fixture (tests/fixtures/z80_voltage_regulator_table.pdf) is a page of a
scanned book with a poorly OCR'd text layer: the electrical characteristics
of the uA7812 and uA7912 regulators, each a table ruled on white paper -
CHARACTERISTICS / CONDITIONS / MIN / TYP / MAX / UNITS - under its
"ELECTRICAL CHARACTERISTICS:" line and over its caption ("Figure 1.14 ...",
"Figure 1.15 ...").

Three faults lost the page, one behind another:

- its small cells crowded with type were taken for boxes of colour (the
  grey of their letters' edges read as a fill), and the page from the
  first table's CONDITIONS column to the second table's foot became one
  box table - both tables and the caption between them, the label column
  left out;
- read as ruled tables, a cell's box at its very foot was turned upside
  down (_deflate_boxes), the table analyzer failed, and every table of the
  page went with it;
- the build stopped at an underscore OCR read on its own ("\\_", no
  height), which \\resizebox could not scale ("Division by 0").

And, once the page was read, its rows:

- four rows of the tables were tombstoned as scan noise before any table
  was found (an operator between a letter and a figure, "*" for a degree
  sign, a 0 for an O read as debris);
- the label printed across the sub-rule of the first table's last row,
  "Average Temperature Coefficient of Output Voltage", was set twice, one
  copy over the other, and stretched over "IOUT = 5 mA" beside it;
- the second table lost its head and first rows to the rule against long
  lines of one column, though its rows are of six cells;
- its head's MIN, TYP and UNITS were set down on the rule under it, and
  its TYP and MAX of the first row came as one cell.

The test asks that the page holds the two tables, the first with its label
column and none of the second's rows; that each caption is a caption, not
a row of a table; that every row is there and set once, the second
table's head its first row; and that the page-aware build compiles, keeps
the page one page, sets that head on one line and the label clear of
"IOUT" beside it.
"""

import re
from pathlib import Path

import pytest

from src.krm.models import CaptionBlock, KnowledgeDocument, TableBlock
from tests.e2e.test_paragraph_overlay import _build_pdf, _extract

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "z80_voltage_regulator_table.pdf"

# The first table's label column, as OCR reads it surely.
LABELS_7812 = ["Output Voltage", "Line Regulation", "Load Regulation", "Short Circuit Current"]
# The second's, likewise.
LABELS_7912 = ["Output Voltage", "Ripple Rejection", "Short Circuit Current"]
# Where the label column's text starts on the page (a share of its width).
LABEL_X0 = 0.328


def _live(doc: KnowledgeDocument, kind) -> list:
    out = []

    def walk(node):
        for child in getattr(node, "children", None) or []:
            if isinstance(child, kind) and not child.is_tombstoned:
                out.append(child)
            walk(child)

    for root in doc.root_containers:
        walk(root)
    return out


def _letters(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def _cells(table: TableBlock) -> list:
    return [
        _letters(" ".join(sp.text for unit in cell.content for il in unit.inlines for sp in il.spans))
        for row in table.grid for cell in row
    ]


@pytest.fixture(scope="module")
def page():
    return _extract(FIXTURE)


def test_the_page_holds_its_two_tables(page):
    tables = sorted(_live(page, TableBlock), key=lambda t: t.visual_layout.bounding_box.y0)
    assert len(tables) == 2, [t.visual_layout.bounding_box for t in tables]
    first, second = tables
    assert not first.metadata.get("box_grid") and not second.metadata.get("box_grid")

    # each with its label column
    for table, labels in ((first, LABELS_7812), (second, LABELS_7912)):
        assert table.visual_layout.bounding_box.x0 <= LABEL_X0
        cells = _cells(table)
        missing = [label for label in labels if not any(_letters(label) in cell for cell in cells)]
        assert not missing, f"labels not in the table: {missing}"

    # the first is the uA7812's alone: none of the uA7912's rows
    assert first.visual_layout.bounding_box.y1 < second.visual_layout.bounding_box.y0
    assert not any("7912" in cell or "126" == cell for cell in _cells(first))


def test_each_caption_is_a_caption(page):
    captions = [c.caption_text for c in _live(page, CaptionBlock)]
    for number in ("1.14", "1.15"):
        assert any(text.startswith(f"Figure {number}") for text in captions), captions
    for table in _live(page, TableBlock):
        assert not any("characteristicsofthe" in cell for cell in _cells(table))


def test_the_page_is_built_as_one_page(page, tmp_path):
    fitz = pytest.importorskip("pymupdf")
    pdf_path = Path(_build_pdf(page, str(tmp_path), "spec_table_page"))
    assert len(fitz.open(pdf_path)) == 1, "the page ran onto another"


def _tables_top_down(page) -> list:
    return sorted(_live(page, TableBlock), key=lambda t: t.visual_layout.bounding_box.y0)


def test_every_row_is_there_and_set_once(page):
    first, second = _tables_top_down(page)
    cells = _cells(first)
    # the label over the sub-rule, once
    assert sum("averagetemperature" in cell for cell in cells) == 1, cells
    # the rows scan_noise had dropped (as OCR reads them)
    for row in ("16vvn22v", "5mal0ut1joa", "55ctj25c"):
        assert any(row in cell for cell in cells), (row, cells)
    assert any(cell == "tj25c" for cell in _cells(second)), _cells(second)


def test_the_second_table_s_head_is_its_first_row(page):
    _, second = _tables_top_down(page)
    head = [_letters(" ".join(sp.text for unit in c.content for il in unit.inlines for sp in il.spans))
            for c in second.grid[0]]
    for word in ("characteristics", "conditions", "min", "max", "units"):
        assert word in head, head
    # its first row's TYP and MAX ("-12 0", "-12.6"), each its own
    first_row = [_letters(" ".join(sp.text for unit in c.content for il in unit.inlines for sp in il.spans))
                 for c in second.grid[1]]
    assert "120" in first_row and "126" in first_row, first_row


def test_the_rebuild_sets_the_head_on_one_line_and_the_label_clear(page, tmp_path):
    fitz = pytest.importorskip("pymupdf")
    pdf_path = Path(_build_pdf(page, str(tmp_path), "spec_table_rows"))
    words = fitz.open(pdf_path)[0].get_text("words")

    def second(text):
        found = sorted((w for w in words if w[4] == text), key=lambda w: w[1])
        assert len(found) >= 2, f"{text!r} set {len(found)} times"
        return found[1]

    def middle(w):
        return (w[1] + w[3]) / 2

    head = second("CHARACTERISTICS")
    for word in ("MIN", "MAX", "UNITS"):
        assert abs(middle(second(word)) - middle(head)) <= 1.5, f"{word!r} off its head's line"
    # the label ends before "IOUT" beside it begins ("'OUT" as OCR read it)
    iout = next(w for w in words if w[4] == "'OUT")
    label = [w for w in words if abs(middle(w) - middle(iout)) < 3 and w[0] < iout[0]]
    assert any(w[4] == "Average" for w in label), [w[4] for w in label]
    assert max(w[2] for w in label) <= iout[0], f"the label runs {max(w[2] for w in label) - iout[0]:.1f}pt into IOUT"
