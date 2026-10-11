"""DiagramDetectorAnalyzer on a scanned page: a figure found by the page's
own ink, and the lines of the page's text that go into it.

The page is drawn here - a paragraph, a heading over a drawing, a label at
the drawing's top, a table's row beside it that OCR set on one line with a
label of the drawing's - and its blocks are given as the pipeline hands
them over: each line with its place, and its print (PrintedLinesAnalyzer).
"""

import pytest

from src.analyzers.diagram import DiagramDetectorAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    DiagramBlock,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)

_PAGE = 400.0    # the page's width and height, pt
_BODY = 10.0     # its body size, pt


def _block(pymupdf, page, lines, size: float = _BODY, bold: bool = False) -> ParagraphBlock:
    """A block of lines - (text, left, baseline) each, pt - printed on the
    page in the given size, with each line's place and print."""
    inlines, printed, boxes = [], [], []
    for text, left, baseline in lines:
        page.insert_text((left, baseline), text, fontname="hebo" if bold else "helv", fontsize=size)
        width = pymupdf.get_text_length(text, "hebo" if bold else "helv", size)
        box = [left / _PAGE, (baseline - 0.75 * size) / _PAGE, (left + width) / _PAGE, (baseline + 0.22 * size) / _PAGE]
        boxes.append(box)
        inlines.append(TextLineInline(
            spans=[StyledTextSpan(text=text)],
            visual_layout=VisualLayout(page_or_screen_index=0, bounding_box=NormalizedRect(*box)),
        ))
        printed.append({"text": text, "page": 0, "box": box, "size": size, "bold": bold, "italic": False,
                        "words": [], "page_pt": [_PAGE, _PAGE]})
    block = ParagraphBlock(
        inlines=inlines,
        visual_layout=VisualLayout(page_or_screen_index=0, bounding_box=NormalizedRect(
            min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))),
    )
    block.metadata["printed_lines"] = printed
    return block


def _text(block) -> str:
    return " / ".join(sp.text for il in block.inlines for sp in il.spans)


@pytest.fixture
def page(tmp_path):
    """The page's blocks by name, its document, analyzed."""
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("cv2")
    pdf = pymupdf.open()
    sheet = pdf.new_page(width=_PAGE, height=_PAGE)

    blocks = {
        "text": _block(pymupdf, sheet, [
            ("The test load is the circuit drawn under this paragraph of the page,", 40, 50),
            ("and the conditions of the test stand in the table that runs beside it.", 40, 62),
            ("Speed measurements are made at the levels the table names for them.", 40, 74),
        ]),
        "heading": _block(pymupdf, sheet, [("TEST LOAD CIRCUIT:", 200, 148)], bold=True),
        # at the wire's end, in the body's size
        "label": _block(pymupdf, sheet, [("Vcc", 240, 167)]),
        # a row of the table beside the drawing, and the drawing's "Y6" on its line
        "row": _block(pymupdf, sheet, [("Active HIGH", 60, 240)]),
    }
    pin = _block(pymupdf, sheet, [("Y6", 188, 240)], size=5.0)
    blocks["row"].inlines += pin.inlines
    blocks["row"].metadata["printed_lines"] += pin.metadata["printed_lines"]
    blocks["row"].visual_layout.bounding_box = NormalizedRect(60 / _PAGE, 0.58, 196 / _PAGE, 0.61)

    # the drawing: a box, a wire across it corner to corner, its outputs
    sheet.draw_rect(pymupdf.Rect(200, 170, 300, 300), color=(0, 0, 0), width=1)
    sheet.draw_line((200, 170), (300, 300), color=(0, 0, 0), width=1)
    sheet.draw_line((300, 200), (330, 200), color=(0, 0, 0), width=1)
    sheet.draw_line((330, 200), (330, 260), color=(0, 0, 0), width=1)

    path = tmp_path / "page.pdf"
    pdf.save(path)
    root = ContainerUnit(title="Book", children=[blocks[name] for name in ("text", "heading", "label", "row")])
    doc = KnowledgeDocument(title="Book", source_uri=f"file://{path}", root_containers=[root])
    DiagramDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    blocks["root"] = root
    blocks["figures"] = [c for c in root.children if isinstance(c, DiagramBlock)]
    return blocks


def test_a_drawing_is_found_by_its_ink_with_no_caption_by_it(page):
    assert len(page["figures"]) == 1
    box = page["figures"][0].visual_layout.bounding_box
    # its strokes, with the labels by them
    assert (box.x0, box.x1) == pytest.approx((188 / _PAGE, 330 / _PAGE), abs=0.01)
    assert (box.y0, box.y1) == pytest.approx((160 / _PAGE, 300 / _PAGE), abs=0.01)
    assert page["figures"][0].metadata["printed_ink"]["runs"]


def test_the_page_s_text_by_a_drawing_stays_the_page_s(page):
    assert not page["text"].is_tombstoned
    # a heading a line and a half over it, in the body's size
    assert not page["heading"].is_tombstoned


def test_a_label_touching_the_drawing_is_its_own_whatever_its_size(page):
    assert page["label"].is_tombstoned
    assert "Vcc" in [label["text"] for label in page["figures"][0].labels]


def test_a_block_loses_the_lines_that_stand_in_the_figure(page):
    row = page["row"]
    assert not row.is_tombstoned
    assert _text(row) == "Active HIGH"
    assert [line["text"] for line in row.metadata["printed_lines"]] == ["Active HIGH"]
    assert row.visual_layout.bounding_box.x1 < 188 / _PAGE
    assert "Y6" in [label["text"] for label in page["figures"][0].labels]


def test_a_figure_stands_in_the_document_under_what_is_over_it(page):
    figure = page["figures"][0]
    children = [id(c) for c in page["root"].children]
    # under its heading - the row beside it stands beside, not over
    assert children.index(id(figure)) == children.index(id(page["heading"])) + 1
    assert figure.parent_container_id == page["root"].id
