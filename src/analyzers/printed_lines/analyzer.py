"""printed_lines: The analyzer itself: orchestration and KRM writes.

A scanned page's lines are printed lines: where each breaks, how far apart
they stand, the type they are set in. Its text layer says none of it -
tesseract sizes a line from its own box and calls nothing bold. This reads
each line's print off the page's pixels (printed.read_printed_lines), all
the lines of a page together - one line alone is too short to tell a bold
from a heavily printed regular - and records it on the line's block
(metadata["printed_lines"], in the block's line order), beside its text,
not in it. HeadingAnalyzer takes a bold line standing alone for a heading;
the builder sets a paragraph by its own lines rather than break them anew.

Only on a scanned page - one an image covers - whose print is the page's
only record of its layout. A born-digital page's text layer says it all.
Early, once text is there (OCRAnalyzer), before anything judges by it.
"""

from typing import Any, Dict, List, Optional

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.analyzers.printed import read_printed_lines
from src.analyzers.source_io import resolve_source_path
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock, UnknownBlock

# An image covering this share of a page makes it a scan.
_SCAN_COVER = 0.8


class PrintedLinesAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="PrintedLinesAnalyzer",
                version="1.0.0",
                description="Records how each line of a scanned page was printed",
                krm_permissions={KRMPermission.READ, KRMPermission.MUTATE_ATTRIBUTES},
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["OCRAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        blocks: List[Any] = []
        for root in doc.root_containers:
            _collect(root, blocks)
        if not blocks:
            return
        path = resolve_source_path(doc)
        if not path:
            return
        try:
            import numpy as np
            import pymupdf
            source = pymupdf.open(path)
        except Exception:
            return
        try:
            scanned = {i for i in range(source.page_count) if _is_scan(source[i])}
            items = [
                (b, "line", il.visual_layout.page_or_screen_index,
                 (il.visual_layout.bounding_box.x0, il.visual_layout.bounding_box.y0,
                  il.visual_layout.bounding_box.x1, il.visual_layout.bounding_box.y1),
                 " ".join(s.text for s in il.spans if getattr(s, "text", "")).strip())
                for b in blocks for il in (b.inlines or [])
                if getattr(il, "visual_layout", None) is not None
                and il.visual_layout.bounding_box is not None
                and il.visual_layout.page_or_screen_index in scanned
            ]
            for owner, line in read_printed_lines(np, pymupdf, source, [i for i in items if i[4]]):
                md = dict(owner.metadata or {})
                md.setdefault("printed_lines", []).append(line)
                owner.metadata = md
        finally:
            source.close()


def _collect(node: Any, out: List[Any]) -> None:
    if isinstance(node, ContainerUnit):
        for child in node.children:
            _collect(child, out)
    elif type(node) in (UnknownBlock, ParagraphBlock) and not node.is_tombstoned:
        out.append(node)


def _is_scan(page) -> bool:
    """Whether an image covers the page: a scan, its text a layer over it."""
    area = page.rect.width * page.rect.height
    for info in page.get_image_info():
        x0, y0, x1, y1 = info.get("bbox", (0, 0, 0, 0))
        if area and (x1 - x0) * (y1 - y0) >= _SCAN_COVER * area:
            return True
    return False
