"""E2E: the figures the real pipeline reads off scanned book pages, and how
the page-aware build redraws them - the measure of test_paragraph_overlay,
for figures.

Each fixture is one page cut out of a scanned technical book (Zaks
"Programming the Z80", MCS-40 User's Manual, Intel Series 3000 Reference
Manual). Its figures were marked off the printed page by eye: where each
stands on the page (its drawing, with the labels and notes inside it -
not its caption, not the text beside it), and a line of text by it - its
caption, else the heading over it - the figure is placed by.

The page goes through the whole pipeline (PdfSourceAdapter, every
analyzer) and the page-aware build. The test asks that

- the document's figures on the page are the expected ones - none missed,
  none made of what is no figure - each standing where the page's does
  (_MIN_IOU);
- nothing of a figure is left as text: no line of another block of the
  page - no cell of a table - stands inside it;
- the rebuilt page draws each as it printed: the figure cut out of the
  source page and out of the rebuild - there by its place against the
  line by it, at the scale that line was set (_laid_over) - laid over
  one another as ink (_paragraph_mismatch), miss no more than
  MAX_MISMATCH of it.
"""

from pathlib import Path

import pytest

from src.krm.models import ContainerUnit, EphemeraBlock, FigureBlock, KnowledgeDocument
from tests.e2e.test_paragraph_overlay import (
    _build_pdf, _extract, _paragraph_mismatch, _paragraph_rect, _run_on_page,
)
from tests.e2e.test_visual_overlay import _render_crop

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "figure"

# Each figure: where it stands on its page (x0, y0, x1, y1, shares of the
# page's width and height), and the line of text by it.
EXPECTED = {
    # a figure over its caption, text over and under them
    "zaks_49.pdf": [((0.145, 0.352, 0.900, 0.710), 'Fig. 2.2: "Standard" Microprocessor Architecture')],
    # two drawings under one caption, a label over each - the note under
    # them is left to the page or the figure
    "zaks_50.pdf": [((0.160, 0.305, 0.820, 0.578), "Fig. 2.3: Shift and Rotate")],
    # a figure at the page's head, under its running head
    "zaks_72.pdf": [((0.115, 0.080, 0.770, 0.365), "Fig. 2.19: The Instruction Arrives from the Memory into IR")],
    # a timing diagram, its caption no "Figure N"
    "mcs40_x.pdf": [((0.225, 0.645, 0.820, 0.915), "4040 Basic Timing Diagram")],
    # a timing diagram with its notes, between two rules across the page
    "mcs40_1-2.pdf": [((0.180, 0.590, 0.915, 0.905), "Figure 1-2. 4004 Basic Instruction Cycle.")],
    # a block diagram under two of three columns, the third running by it;
    # placed by the last line over it - its caption's words read apart in
    # the rebuild, set letter by letter ("F igure", "Diagra m")
    "intel3000_2-17.pdf": [((0.360, 0.535, 0.850, 0.880), "executing I/O operations.")],
    # a small circuit under its heading, no caption, tables over and under
    "intel3000_2-22.pdf": [((0.510, 0.625, 0.640, 0.745), "TEST LOAD CIRCUIT:")],
    # a logic diagram under its heading beside a table, no caption
    "intel3000_2-32.pdf": [((0.490, 0.095, 0.940, 0.515), "LOGIC DIAGRAM")],
}

# Share of a figure's ink allowed to miss the other crop's ink.
MAX_MISMATCH = 0.10
# How much of a figure's and its expected place's joint area they share at
# the least (intersection over union): the places were marked by eye, a
# hundredth of the page loose.
_MIN_IOU = 0.8
# How closely a line's width is read off its ink (pt): a quarter point at
# either end (_paragraph_rect reads it at four pixels to the point). And
# in how many steps the scale it leaves open either way is tried.
_WIDTH_READ = 0.5
_SCALE_STEPS = 4


def _blocks(doc: KnowledgeDocument, page_index: int = 0) -> list:
    """The live blocks of one page, containers with a place of their own
    (headings) among them, in the document's order."""
    out = []

    def walk(node):
        if node.is_tombstoned:
            return
        vl = getattr(node, "visual_layout", None)
        if vl is not None and vl.bounding_box is not None and vl.page_or_screen_index == page_index:
            out.append(node)
        for child in getattr(node, "children", None) or []:
            walk(child)

    for root in doc.root_containers:
        walk(root)
    return out


def _box(node) -> tuple:
    bb = node.visual_layout.bounding_box
    return (bb.x0, bb.y0, bb.x1, bb.y1)


def _iou(a: tuple, b: tuple) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    shared = w * h
    return shared / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - shared)


def _rounded(box: tuple) -> tuple:
    return tuple(round(float(v), 3) for v in box)


def _inside(box: tuple, region: tuple) -> bool:
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return region[0] <= x <= region[2] and region[1] <= y <= region[3]


def _text_places(node) -> list:
    """Where a block's text stands, piece by piece: a table's cells; else
    its lines, where they have places of their own; else the block."""
    cells = [cell for row in getattr(node, "grid", None) or [] for cell in row]
    pieces = cells or getattr(node, "inlines", None) or []
    placed = [_box(p) for p in pieces
              if getattr(p, "visual_layout", None) is not None and p.visual_layout.bounding_box is not None]
    return placed or [_box(node)]


def _label(node) -> str:
    text = getattr(node, "title", "") or " ".join(
        getattr(s, "text", "") for il in getattr(node, "inlines", None) or [] for s in getattr(il, "spans", []))
    return f"{type(node).__name__} {text[:40]!r}"


def _line_rect(fitz, pdf_path: Path, text: str):
    """Where a line of text prints in a PDF, read off its ink
    (_paragraph_rect): (page index, rect) on the page it is found best."""
    doc = fitz.open(pdf_path)
    found = [(i, _run_on_page(doc[i], text.split())) for i in range(len(doc))]
    found = [(i, run) for i, run in found if run]
    if not found:
        return None, None
    page, run = max(found, key=lambda ir: len(ir[1]))
    return page, _paragraph_rect(fitz, doc[page], run)


def _laid_over(fitz, path: Path, pdf_path: Path, out_page: int, region, src_line, out_line) -> float:
    """How much of a figure's ink misses, the figure cut out of the source
    page (region, a rect there) and out of the rebuild laid over one
    another: in the rebuild it is cut by its place against the line by it
    (src_line and out_line, the line's rects on either), at the scale the
    line was set at.

    That scale is the line's two widths' ratio, and they are read to
    _WIDTH_READ between them: a line a hundred points wide tells it to
    half a hundredth, and a figure four hundred points across then lands
    two points off at its far side - the MCS-40 manual's 4004 instruction
    cycle, drawn in place, read 22% off. So the scale is tried across what
    the widths leave open, and the figure is where it lies best."""
    source = _render_crop(fitz, path, 0, region)
    least = 1.0
    for step in range(-_SCALE_STEPS, _SCALE_STEPS + 1):
        scale = (out_line.width + step * _WIDTH_READ / _SCALE_STEPS) / src_line.width
        rect = fitz.Rect(
            out_line.x0 + (region.x0 - src_line.x0) * scale, out_line.y1 + (region.y0 - src_line.y1) * scale,
            out_line.x0 + (region.x1 - src_line.x0) * scale, out_line.y1 + (region.y1 - src_line.y1) * scale,
        )
        least = min(least, _paragraph_mismatch(source, _render_crop(fitz, pdf_path, out_page, rect)))
    return least


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_figures_are_found_and_redrawn_as_printed(tmp_path, fixture):
    fitz = pytest.importorskip("pymupdf")
    pytest.importorskip("PIL")
    path = FIXTURES / fixture
    expected = EXPECTED[fixture]

    doc = _extract(path)
    blocks = _blocks(doc)
    figures = [b for b in blocks if isinstance(b, FigureBlock)]

    # each expected figure found where it stands, nothing else taken for one
    found = [_rounded(_box(f)) for f in figures]
    left = list(found)
    missed = []
    for region, anchor in expected:
        best = max(left, key=lambda box: _iou(box, region), default=None)
        if best is not None and _iou(best, region) >= _MIN_IOU:
            left.remove(best)
        else:
            missed.append(anchor)
    assert not missed and not left, (
        f"{fixture}: figures not found where they stand - {missed}; taken for figures that are none - {left}; "
        f"found {found}"
    )

    # nothing of a figure left as text
    stray = [
        _label(b) for b in blocks
        if not isinstance(b, (FigureBlock, EphemeraBlock))
        and not (isinstance(b, ContainerUnit) and not b.title)
        and any(_inside(place, region) for place in _text_places(b) for region, _ in expected)
    ]
    assert not stray, f"{fixture}: left as text inside a figure - {stray}"

    # each redrawn as it printed, by the line by it
    pdf_path = Path(_build_pdf(doc, str(tmp_path), "figure_overlay_doc"))
    src_page = fitz.open(path)[0]
    pw, ph = src_page.rect.width, src_page.rect.height
    misses = []
    for region, anchor in expected:
        _, src_line = _line_rect(fitz, path, anchor)
        out_page, out_line = _line_rect(fitz, pdf_path, anchor)
        assert src_line is not None, f"{fixture}: {anchor!r} not found on the source page"
        assert out_line is not None, f"{fixture}: {anchor!r} not found in the assembled document"
        src_rect = fitz.Rect(region[0] * pw, region[1] * ph, region[2] * pw, region[3] * ph)
        mismatch = _laid_over(fitz, path, pdf_path, out_page, src_rect, src_line, out_line)
        if mismatch > MAX_MISMATCH:
            misses.append(f"{anchor!r}: {mismatch:.1%}")
    assert not misses, (
        f"{fixture}: {len(misses)} of {len(expected)} figures miss more than {MAX_MISMATCH:.0%} of their ink "
        f"against the source - overlaid, they do not line up: " + "; ".join(misses)
    )
