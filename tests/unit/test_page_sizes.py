"""The page's own size travels with the document (RFC 0021 §3).

Every bbox is normalised to its page, so the page size is what turns it and a
font size in points back into a layout. The editor used to assume A4 for
every page: on a scan of another size ("Programming the Z80") each line of
the reconstruction came out too small beside the scan under it.
"""
import io

import pytest

from src.adapters.pdf_adapter import PdfSourceAdapter
from src.assembler.page_assembler import page_layout_map
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def test_the_adapter_records_each_pages_size():
    fitz = pytest.importorskip("pymupdf")
    src = fitz.open()
    src.new_page(width=612, height=792).insert_text((72, 100), "Letter page")
    src.new_page(width=432, height=648).insert_text((72, 100), "A smaller page")
    doc = PdfSourceAdapter().parse(io.BytesIO(src.tobytes()), "file://sizes.pdf")
    assert doc.metadata["page_sizes_pt"] == [[612.0, 792.0], [432.0, 648.0]]


def test_the_page_layout_carries_the_size():
    para = ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text="Body")])],
        visual_layout=VisualLayout(bounding_box=NormalizedRect(0.1, 0.1, 0.9, 0.2),
                                   page_or_screen_index=1),
    )
    doc = KnowledgeDocument(title="t", source_uri="test://",
                            metadata={"page_count": 2, "page_sizes_pt": [[595, 842], [432, 648]]},
                            root_containers=[ContainerUnit(title="book", children=[para])])
    entry = next(p for p in page_layout_map(doc) if p["page_index"] == 1)
    assert (entry["width_pt"], entry["height_pt"]) == (432, 648)
