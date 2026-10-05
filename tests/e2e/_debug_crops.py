"""Debug-only: the two crop locators the older debug scripts were written
against, from before test_visual_overlay cut both crops the same way
(_crop_rects). _source_table_rect is the source crop as it was then - the
table's recorded box grown to its frame - kept so those scripts still run
and still measure what they measured; _output_table_rect is the overlay's
own text locator."""
from pathlib import Path

from src.krm.models import TableBlock
from tests.e2e.test_visual_overlay import _grow_to_frame, _table_rect as _output_table_rect  # noqa: F401


def _source_table_rect(fitz, pdf_path: Path, page_index: int, table: TableBlock):
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    pw, ph = page.rect.width, page.rect.height
    bb = table.visual_layout.bounding_box
    rect = _grow_to_frame(fitz, page, fitz.Rect(bb.x0 * pw, bb.y0 * ph, bb.x1 * pw, bb.y1 * ph))
    doc.close()
    return rect
