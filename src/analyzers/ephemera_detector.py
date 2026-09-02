"""
EphemeraDetectorAnalyzer — detect running headers, footers, and page numbers.

Heuristics:
- Page number: short block (≤5 chars) at page top/bottom (y<0.08 or y>0.92)
  containing only digits or roman numerals.
- Running header/footer: the SAME text at an extreme y position on several
  pages. Repetition is the whole point — a one-off line near the top of a page
  is a page title or a table heading, not a running head, and ephemera are
  dropped from the exported document.
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional

from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    EphemeraBlock,
    KnowledgeDocument,
    ParagraphBlock,
)

_PAGENUM_RE = re.compile(r"^\s*(?:\d{1,4}|[ivxlcdm]{1,8}|[IVXLCDM]{1,8})\s*$")


# A running head repeats; below this it is page-specific content.
MIN_REPEAT_PAGES = 2


def _block_text(block: ParagraphBlock) -> str:
    """Full text of the block, across every inline.

    Not just the first span: a block holds one inline per source line, so the
    first span is a fragment ("Analysis"), and judging length or identity by it
    mistakes long headings for short running heads.
    """
    parts = [
        str(getattr(span, "text", ""))
        for inline in (block.inlines or [])
        for span in (getattr(inline, "spans", []) or [])
        if getattr(span, "text", "")
    ]
    return " ".join(parts).strip()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _is_edge(bbox: Any) -> bool:
    """At the very top or bottom of the page, where running heads sit."""
    return bbox.y0 < 0.06 or bbox.y1 > 0.94


class EphemeraDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="EphemeraDetectorAnalyzer",
                version="1.0.0",
                description="Detect running headers/footers/page numbers and promote to EphemeraBlock",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.MUTATE_ATTRIBUTES,
                },
                rg_permissions=set(),
                kg_permissions={KGPermission.READ},
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
        # A running head is defined by repeating. Collect what actually repeats
        # before promoting anything, so page titles, section headings and table
        # captions near a page edge are not dropped as decoration.
        seen: Dict[str, set] = {}
        for root in doc.root_containers:
            self._collect(root, seen)
        self._repeated = {t for t, pages in seen.items()
                          if len(pages) >= MIN_REPEAT_PAGES}
        for root in doc.root_containers:
            self._process(root)

    def _collect(self, container: ContainerUnit, seen: Dict[str, set]) -> None:
        """Record which pages each candidate line appears on."""
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._collect(child, seen)
                continue
            if type(child) is not ParagraphBlock or child.is_tombstoned:
                continue
            vl = child.visual_layout
            if not vl or not vl.bounding_box:
                continue
            if not _is_edge(vl.bounding_box):
                continue
            text = _block_text(child)
            if not text or len(text) >= 80:
                continue
            seen.setdefault(_norm(text), set()).add(vl.page_or_screen_index)

    def _process(self, container: ContainerUnit) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child)

        new_children: List[Any] = []
        for child in container.children:
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                new_children.append(child)
                continue
            if type(child) is not ParagraphBlock:
                new_children.append(child)
                continue

            vl = child.visual_layout
            if not vl or not vl.bounding_box:
                new_children.append(child)
                continue

            y0 = vl.bounding_box.y0
            y1 = vl.bounding_box.y1
            text = _block_text(child)

            if not text:
                new_children.append(child)
                continue

            if (y0 < 0.08 or y1 > 0.92) and _PAGENUM_RE.match(text):
                eph = EphemeraBlock(
                    ephemera_type="page_number",
                    repeated_text=text.strip(),
                    visual_layout=child.visual_layout,
                    extraction_confidence=child.extraction_confidence,
                    classification_confidence=0.9,
                    confidence_score=min(child.extraction_confidence, 0.9),
                )
                eph.id = child.id
                new_children.append(eph)
                continue

            repeated = _norm(text) in self._repeated
            if y0 < 0.06 and len(text) < 80 and repeated:
                eph = EphemeraBlock(
                    ephemera_type="header",
                    repeated_text=text.strip(),
                    visual_layout=child.visual_layout,
                    extraction_confidence=child.extraction_confidence,
                    classification_confidence=0.75,
                    confidence_score=min(child.extraction_confidence, 0.75),
                )
                eph.id = child.id
                new_children.append(eph)
                continue

            if y1 > 0.94 and len(text) < 80 and repeated:
                eph = EphemeraBlock(
                    ephemera_type="footer",
                    repeated_text=text.strip(),
                    visual_layout=child.visual_layout,
                    extraction_confidence=child.extraction_confidence,
                    classification_confidence=0.75,
                    confidence_score=min(child.extraction_confidence, 0.75),
                )
                eph.id = child.id
                new_children.append(eph)
                continue

            new_children.append(child)

        container.children = new_children
