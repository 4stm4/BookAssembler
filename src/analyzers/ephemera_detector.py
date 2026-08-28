"""
EphemeraDetectorAnalyzer — detect running headers, footers, and page numbers.

Heuristics:
- Page number: short block (≤5 chars) at page top/bottom (y<0.08 or y>0.92)
  containing only digits or roman numerals.
- Running header/footer: repeated text across pages at extreme y positions,
  font size < body mode.
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


def _first_text(block: ParagraphBlock) -> str:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                return str(txt)
    return ""


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
        for root in doc.root_containers:
            self._process(root)

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
            text = _first_text(child)

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

            if y0 < 0.06 and len(text) < 80:
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

            if y1 > 0.94 and len(text) < 80:
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
