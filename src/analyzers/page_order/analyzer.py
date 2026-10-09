"""page_order: The analyzer itself: orchestration and KRM writes.

A scanned page's text layer lists its blocks as its OCR found them: the
Intel 3000 manual's A.C. characteristics page whole column by whole
column, "CAPACITANCE" under the left half before "TEST LOAD CIRCUIT:"
beside "TEST CONDITIONS:" over it. What is built out of the document's
order - a heading's section, the paragraphs under it - follows that. Each
scanned page's blocks are put in the order the page is read
(rules.reading_order): its columns one after another, the bands between
what runs across them one under another. A born-digital page's text
comes in the order it was written.
"""

from typing import Any, Dict, List, Optional

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.analyzers.page_order.rules import reading_order
from src.analyzers.page_order.signals import BACKDROP_COVER, GUTTER_LINES
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument


class PageOrderAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="PageOrderAnalyzer",
                version="1.0.0",
                description="Orders a scanned page's blocks as the page is read",
                krm_permissions={KRMPermission.READ, KRMPermission.MUTATE_ATTRIBUTES},
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["PrintedLinesAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        for root in doc.root_containers:
            root.children = _in_order(root.children)


def _in_order(children: List[Any]) -> List[Any]:
    """children with each scanned page's run of blocks in reading order."""
    out: List[Any] = []
    k = 0
    while k < len(children):
        page = _page(children[k])
        end = k + 1
        while end < len(children) and page is not None and _page(children[end]) == page:
            end += 1
        run = children[k:end]
        out.extend(_page_in_order(run) if page is not None else run)
        k = end
    return out


def _page(node: Any) -> Optional[int]:
    if isinstance(node, ContainerUnit):
        return None
    vl = getattr(node, "visual_layout", None)
    if vl is None or vl.bounding_box is None:
        return None
    return vl.page_or_screen_index


def _page_in_order(blocks: List[Any]) -> List[Any]:
    """One page's blocks in reading order - a scanned page's (its blocks'
    printed lines, PrintedLinesAnalyzer); the scan behind them and what is
    tombstoned first, as they came."""
    printed = [l for b in blocks for l in (b.metadata or {}).get("printed_lines") or []]
    if not printed:
        return blocks
    laid = [b for b in blocks if not b.is_tombstoned and _area(b) < BACKDROP_COVER]
    if len(laid) < 2:
        return blocks
    page_h = printed[0]["page_pt"][1]
    page_w = printed[0]["page_pt"][0]
    heights = sorted((l["box"][3] - l["box"][1]) * page_h for l in printed)
    gutter = GUTTER_LINES * heights[len(heights) // 2] / page_w
    boxes = [(bb.x0, bb.y0, bb.x1, bb.y1) for bb in (b.visual_layout.bounding_box for b in laid)]
    rest = [b for b in blocks if not any(b is l for l in laid)]
    return rest + [laid[k] for k in reading_order(boxes, gutter)]


def _area(block: Any) -> float:
    bb = block.visual_layout.bounding_box
    return (bb.x1 - bb.x0) * (bb.y1 - bb.y0)
