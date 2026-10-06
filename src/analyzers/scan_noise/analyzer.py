"""scan_noise: The analyzer itself: orchestration and KRM writes."""

from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.access import block_text
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock, UnknownBlock

from src.analyzers.scan_noise.rules import is_scan_noise, is_squeezed


class ScanNoiseAnalyzer(BaseAnalyzer):
    """Tombstones letter debris that a scan's text layer made of a logo,
    crest or smudge, before it can pollute headings or the title page.

    This used to happen inside the PDF adapter, which dropped such blocks
    outright. That is a judgement about content, not conversion (RFC 0008
    §5.2), and it deleted without a trace (RFC 0001 §2.4) — measured on the
    test books it also discarded every dotted-leader contents line and every
    Cyrillic paragraph without a Latin word in it.
    """

    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="ScanNoiseAnalyzer",
                version="1.0.0",
                description="Tombstones letter debris from scanned non-text regions",
                krm_permissions={KRMPermission.READ, KRMPermission.TOMBSTONE},
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["NormalizationAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        sizes = (doc.metadata or {}).get("page_sizes_pt") or []
        for container in doc.root_containers:
            self._process(container, sizes)

    def _process(self, container: ContainerUnit, sizes: List[Any]) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child, sizes)
            elif (
                type(child) in (ParagraphBlock, UnknownBlock)
                and not child.is_tombstoned
                and (is_scan_noise(block_text(child)) or is_squeezed(_lines_pt(child, sizes)))
            ):
                child.is_tombstoned = True
                if not child.metadata:
                    child.metadata = {}
                child.metadata["tombstone_reason"] = "scan_noise"


def _lines_pt(block: Any, sizes: List[Any]) -> List[Tuple[str, float, float]]:
    """A block's lines as (text, width, height) in points, where its page's
    size is known."""
    out: List[Tuple[str, float, float]] = []
    for il in block.inlines or []:
        vl = getattr(il, "visual_layout", None)
        if vl is None or vl.bounding_box is None or vl.page_or_screen_index is None:
            continue
        if vl.page_or_screen_index >= len(sizes) or not sizes[vl.page_or_screen_index]:
            continue
        pw, ph = sizes[vl.page_or_screen_index][:2]
        b = vl.bounding_box
        text = "".join(getattr(s, "text", "") for s in il.spans)
        out.append((text, (b.x1 - b.x0) * pw, (b.y1 - b.y0) * ph))
    return out
