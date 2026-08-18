"""
DiagramDetectorAnalyzer — detects schematic diagrams on scanned pages.

Scanned figures (block diagrams, flowcharts) arrive as many short text labels
(Instruction, Datum, Register, EA*, …) scattered over a page region, with the
lines/arrows living only on the page raster. This analyzer clusters those short
labels into a single DiagramBlock that references the page region, so the diagram
can be reconstructed from the scan with every label preserved (RFC 0002/0008 §5.2:
detection is analysis, not adapter work; RFC 0001 §2.4: absorbed labels are
tombstoned, never deleted).
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    DiagramBlock,
    KnowledgeDocument,
    ParagraphBlock,
    VisualLayout,
    NormalizedRect,
)

log = logging.getLogger(__name__)

# A real figure caption block starts with "Figure N-M" / "Fig. N.M".
_RE_FIGURE_CAPTION = re.compile(r"^fig(?:ure|\.)?\s*\d+[-.–]\d+", re.IGNORECASE)
_RE_SUBLABEL = re.compile(r"^\(?[a-g]\)?\s+\w", re.IGNORECASE)  # (a) Immediate

MIN_LABELS = 6          # min short labels in a region to call it a diagram
MAX_LABEL_WORDS = 4     # a "label" is a short text block
MAX_LABEL_WIDTH = 0.30  # schematic labels are narrow; body text spans wider
# Graphic boxes/arrows extend past the text labels, so pad generously — most on
# the right where destination boxes (Memory/Datum) sit beyond the last label.
RIGHT_PAD = 0.17
LEFT_PAD = 0.05
PAD = 0.03


def _text_of(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts).strip()


def _bbox_of(block: Any) -> Optional[Tuple[float, float, float, float]]:
    vl = getattr(block, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    if bb is None:
        return None
    return (bb.x0, bb.y0, bb.x1, bb.y1)


def _page_of(block: Any) -> Optional[int]:
    vl = getattr(block, "visual_layout", None)
    return getattr(vl, "page_or_screen_index", None) if vl else None


class DiagramDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="DiagramDetectorAnalyzer",
                version="1.0.0",
                description="Clusters short labels on scanned pages into DiagramBlocks",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
                },
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
        # Collect leaf paragraph blocks with their parent container, by page.
        by_page: Dict[int, List[Tuple[ParagraphBlock, ContainerUnit]]] = {}

        def walk(container: ContainerUnit) -> None:
            for child in container.children:
                if getattr(child, "is_tombstoned", False):
                    continue
                if isinstance(child, ContainerUnit):
                    walk(child)
                elif isinstance(child, ParagraphBlock) and not isinstance(child, DiagramBlock):
                    pg = _page_of(child)
                    if pg is not None and _bbox_of(child) is not None:
                        by_page.setdefault(pg, []).append((child, container))

        for c in doc.root_containers:
            walk(c)

        count = 0
        for pg, items in by_page.items():
            count += self._detect_on_page(pg, items)
        if count:
            log.info("DiagramDetectorAnalyzer: %d diagram(s) detected", count)

    def _detect_on_page(
        self, page: int, items: List[Tuple[ParagraphBlock, ContainerUnit]]
    ) -> int:
        if len(items) < MIN_LABELS:
            return 0

        caption_text = ""
        labels: List[Tuple[ParagraphBlock, ContainerUnit, str, Tuple[float, float, float, float]]] = []
        for block, parent in items:
            txt = _text_of(block)
            if not txt:
                continue
            # A real caption is short ("Figure 2-11 Data-related addressing modes"),
            # not an in-text reference ("Figure 2-5 shows how a program's code …").
            if not caption_text and _RE_FIGURE_CAPTION.match(txt) and len(txt.split()) <= 10:
                caption_text = txt
            bb = _bbox_of(block)
            if not bb:
                continue
            width = bb[2] - bb[0]
            is_sublabel = bool(_RE_SUBLABEL.match(txt))
            # A schematic label is a short AND narrow text block (or an (a)-(g)
            # sub-caption). Wide blocks are body text and are excluded.
            is_label = (len(txt.split()) <= MAX_LABEL_WORDS and width <= MAX_LABEL_WIDTH) or is_sublabel
            if is_label:
                labels.append((block, parent, txt, bb))

        # A diagram region needs a real Figure caption and a cluster of narrow labels.
        if not caption_text or len(labels) < MIN_LABELS:
            return 0

        # Region = bbox of all clustered labels, padded (extra on the right for
        # arrows/boxes that extend beyond the text labels).
        x0 = min(b[3][0] for b in labels)
        y0 = min(b[3][1] for b in labels)
        x1 = max(b[3][2] for b in labels)
        y1 = max(b[3][3] for b in labels)
        region = NormalizedRect(
            max(0.0, x0 - LEFT_PAD), max(0.0, y0 - PAD),
            min(1.0, x1 + RIGHT_PAD), min(1.0, y1 + PAD),
        )

        diagram = DiagramBlock(
            caption_text=caption_text,
            labels=[{"text": t, "x0": bb[0], "y0": bb[1], "x1": bb[2], "y1": bb[3]}
                    for _b, _p, t, bb in labels],
            visual_layout=VisualLayout(bounding_box=region, page_or_screen_index=page),
            extraction_confidence=0.85,
            classification_confidence=0.80,
            confidence_score=0.80,
        )

        # Insert the diagram at the position of the first label, tombstone the rest.
        first_parent = labels[0][1]
        first_block = labels[0][0]
        try:
            idx = first_parent.children.index(first_block)
        except ValueError:
            idx = 0
        first_parent.children.insert(idx, diagram)

        for block, parent, _txt, _bb in labels:
            block.is_tombstoned = True
            if not block.metadata:
                block.metadata = {}
            block.metadata["tombstone_reason"] = f"absorbed_into_diagram:{diagram.id}"

        return 1
