"""
CaptionAnalyzer — detects figure/table/example captions and links them.

Per RFC 0005: READ, TRANSFORM_NODE on KRM; READ, MUTATE_EDGES on RG.
Identifies ParagraphBlocks matching caption patterns (e.g. "Figure 1-5 ASCII code.")
and converts them to CaptionBlock, linking to the nearest target block via caption_id.

Also detects ContainerUnit titles matching "Example N" and sets semantic_type='example'.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission, RGPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    CaptionBlock,
    ContainerUnit,
    FigureBlock,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TableBlock,
    TextLineInline,
)

_CAPTION_RE = re.compile(
    r"^(Figure|Fig\.|Table|Example|Пример|Таблица|Рис\.)\s+"
    r"(\d+[-–.]\d+|\d+)\s*(.*)",
    re.IGNORECASE,
)

_EXAMPLE_HEADING_RE = re.compile(
    r"^Example\s+(\d+[-–.]\d+|\d+)",
    re.IGNORECASE,
)

_TARGET_TYPE_MAP = {
    "figure": "figure",
    "fig.": "figure",
    "рис.": "figure",
    "table": "table",
    "таблица": "table",
    "example": "example",
    "пример": "example",
}


def _get_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)


def _find_nearest_target(
    children: list,
    caption_idx: int,
    target_type: str,
) -> Optional[str]:
    """Find the nearest block of matching type before or after caption_idx."""
    best_id = None
    best_dist = float("inf")

    target_classes = {
        "figure": FigureBlock,
        "table": TableBlock,
    }
    cls = target_classes.get(target_type)
    if cls is None:
        return None

    for i, child in enumerate(children):
        if isinstance(child, cls):
            dist = abs(i - caption_idx)
            if dist < best_dist:
                best_dist = dist
                best_id = child.id
    return best_id


class CaptionAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="CaptionAnalyzer",
                version="1.0.0",
                description="Detects captions and links them to figures/tables/examples",
                krm_permissions={KRMPermission.READ, KRMPermission.TRANSFORM_NODE},
                rg_permissions={RGPermission.READ},
                kg_permissions=set(),
                depends_on=["NormalizationAnalyzer", "TableDetectorAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        for container in doc.root_containers:
            self._process_container(container)

    def _process_container(self, container: ContainerUnit) -> None:
        # Tag example containers
        if _EXAMPLE_HEADING_RE.match(container.title or ""):
            container.semantic_type = "example"
            container.classification_confidence = max(
                container.classification_confidence, 0.85
            )
            container.update_confidence()

        for child in list(container.children):
            if isinstance(child, ContainerUnit):
                self._process_container(child)

        replacements: Dict[int, CaptionBlock] = {}

        for idx, child in enumerate(container.children):
            if not isinstance(child, ParagraphBlock):
                continue
            text = _get_text(child).strip()
            match = _CAPTION_RE.match(text)
            if not match:
                continue

            keyword = match.group(1).lower()
            label_num = match.group(2)
            description = match.group(3).strip()
            target_type = _TARGET_TYPE_MAP.get(keyword, "figure")

            target_id = _find_nearest_target(
                container.children, idx, target_type
            )

            caption = CaptionBlock(
                caption_text=text,
                target_type=target_type,
                label_number=label_num,
                target_block_id=target_id,
                parent_container_id=container.id,
                provenance_info=child.provenance_info,
                visual_layout=child.visual_layout,
                extraction_confidence=child.extraction_confidence,
                classification_confidence=0.90,
            )
            caption.update_confidence()
            replacements[idx] = caption

            # Link caption to target block
            if target_id:
                for c in container.children:
                    if getattr(c, "id", None) == target_id:
                        if hasattr(c, "caption_id"):
                            c.caption_id = caption.id
                        break

        if replacements:
            new_children = []
            for idx, child in enumerate(container.children):
                if idx in replacements:
                    new_children.append(replacements[idx])
                else:
                    new_children.append(child)
            container.children = new_children
