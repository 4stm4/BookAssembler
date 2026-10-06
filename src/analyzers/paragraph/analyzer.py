"""paragraph: The analyzer itself: orchestration and KRM writes.

OCR cuts a paragraph into blocks where its lines stand a little further
apart, or where a bold word thickens one: the paragraph fixture's one
paragraph came out three. The rest of a paragraph - in its column,
unindented, a line under its last full line (rules.continues) - is merged
into it, its lines and their print (metadata["printed_lines"]) after the
paragraph's own, and tombstoned (RFC 0001 §2.4).
"""

from typing import Any, Dict, Optional

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.analyzers.paragraph.rules import continues
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, NormalizedRect, ParagraphBlock


class ParagraphAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="ParagraphAnalyzer",
                version="1.0.0",
                description="Joins the pieces of a paragraph OCR cut apart",
                krm_permissions={KRMPermission.READ, KRMPermission.MUTATE_ATTRIBUTES, KRMPermission.TOMBSTONE},
                rg_permissions=set(),
                kg_permissions=set(),
                # Paragraphs are final only once nothing else can claim them.
                depends_on=["UnknownResolverAnalyzer"],
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
            _join(root)


def _join(container: ContainerUnit) -> None:
    """Merge into each paragraph the paragraphs that continue it."""
    prev: Optional[ParagraphBlock] = None
    for child in container.children:
        if isinstance(child, ContainerUnit):
            _join(child)
            prev = None
            continue
        if getattr(child, "is_tombstoned", False):
            continue
        if type(child) is not ParagraphBlock:
            prev = None
            continue
        if prev is not None and continues(prev, child):
            a, b = prev.visual_layout.bounding_box, child.visual_layout.bounding_box
            prev.inlines = list(prev.inlines or []) + list(child.inlines or [])
            prev.visual_layout.bounding_box = NormalizedRect(
                min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))
            printed = list((prev.metadata or {}).get("printed_lines") or []) + \
                list((child.metadata or {}).get("printed_lines") or [])
            if printed:
                prev.metadata = {**(prev.metadata or {}), "printed_lines": printed}
            child.is_tombstoned = True
            child.metadata = {**(child.metadata or {}), "tombstone_reason": "merged_into_paragraph"}
            continue
        prev = child
