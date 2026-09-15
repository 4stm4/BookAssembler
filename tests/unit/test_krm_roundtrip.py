"""KRM roundtrip: a real PDF page -> PdfSourceAdapter -> TableDetectorAnalyzer.

Fixture: tests/fixtures/z80_decimal_binary_table.pdf, page 20 of "Programming
the Z80" (Fig. 1.2 "Decimal-Binary Table") exported as a real one-page PDF
with its own text layer — no OCR, no network, fully deterministic.

The table's four columns are not laid out as one line per row in the PDF's
own text stream: PyMuPDF gives each column entry its own line, and several
of those lines only happen to share a y-coordinate because they sit side by
side (RFC 0002, UnknownBlock). PdfSourceAdapter groups all of that into a
single UnknownBlock per its own block boundaries (RFC 0008 §5.2: no semantic
splitting in the adapter) — TableDetectorAnalyzer reads that block's own
line geometry, regroups fragments that share a y0 into a visual row, and
sorts each row by x0 into the real column order (src/analyzers/table/rules.py
_table_from_lines / _group_into_rows).

This checks the whole real chain end to end: nothing dropped, no cell
mis-ordered, no silent deletion of the rows absorbed into the table (RFC
0001 SS2.4).
"""

from pathlib import Path

from src.adapters.pdf_adapter import PdfSourceAdapter
from src.analyzers.table import TableDetectorAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import TableBlock, UnknownBlock

FIXTURE_PDF = Path(__file__).parent.parent / "fixtures" / "z80_decimal_binary_table.pdf"

# The table exactly as printed on the page (Fig. 1.2), row by row, left to
# right. A "•" cell is the printed ellipsis marker for an omitted range.
EXPECTED_GRID = [
    ["0", "00000000", "32", "00100000"],
    ["1 00000001", "33", "00100001"],
    ["2", "00000010", "•"],
    ["3 00000011"],
    ["4", "00000100"],
    ["5", "00000101", "63 00111111"],
    ["6", "00000110", "64", "01000000"],
    ["7", "00000111", "65 01000001"],
    ["8 00001000"],
    ["9", "00001001"],
    ["10", "00001010", "127 01111111"],
    ["11 00001011", "128 10000000"],
    ["12", "00001100", "129 10000001"],
    ["13 00001101"],
    ["14", "00001110"],
    ["15 00001111"],
    ["•"],
    ["16", "00010000"],
    ["17", "00010001", "•"],
    ["•"],
    ["•"],
    ["254", "11111110"],
    ["31 00011111", "255", "11111111"],
]


def _grid_texts(table: TableBlock):
    rows = []
    for row in table.grid:
        texts = []
        for cell in row:
            for block in cell.content:
                for inline in block.inlines:
                    for span in inline.spans:
                        texts.append(span.text)
        rows.append(texts)
    return rows


def test_roundtrip_table_block():
    """A real PDF page's table must round-trip through PdfSourceAdapter and
    TableDetectorAnalyzer into a TableBlock matching what is printed on it,
    cell for cell, in reading order."""
    doc = PdfSourceAdapter().parse(
        open(FIXTURE_PDF, "rb"), f"file://{FIXTURE_PDF}"
    )
    container = doc.root_containers[0]

    TableDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

    tables = [c for c in container.children if isinstance(c, TableBlock)]
    assert len(tables) == 1, f"expected exactly one TableBlock, got {len(tables)}"
    table = tables[0]

    assert _grid_texts(table) == EXPECTED_GRID

    # Geometry: the table's own box is the union of its cells (not just the
    # source block's box wholesale), and every cell carries its own bbox
    # (width/height via NormalizedRect) and font (RFC 0002 - TableCell is a
    # BaseKRMNode; src/analyzers/table/rules.py stopped discarding this).
    table_box = table.visual_layout.bounding_box
    assert table_box.width > 0 and table_box.height > 0
    first_row = table.grid[0]
    for cell in first_row:
        assert cell.visual_layout is not None, "cell lost its geometry"
        box = cell.visual_layout.bounding_box
        assert box.width > 0 and box.height > 0
        assert table_box.x0 <= box.x0 and box.x1 <= table_box.x1
        assert table_box.y0 <= box.y0 and box.y1 <= table_box.y1
        assert cell.visual_layout.style is not None, "cell lost its font"
        assert cell.visual_layout.style.font_size_pt > 0
    decimal_cell, binary_cell = first_row[0], first_row[1]
    assert decimal_cell.visual_layout.bounding_box.x1 < binary_cell.visual_layout.bounding_box.x0, (
        "decimal column must sit to the left of the binary column"
    )

    absorbed = [
        c for c in container.children
        if isinstance(c, UnknownBlock) and c.is_tombstoned
    ]
    assert not absorbed, (
        "the table's own block was reclassified in place (RFC 0001 SS2.3), "
        "not absorbed from separate siblings, so nothing here should be "
        "tombstoned"
    )
