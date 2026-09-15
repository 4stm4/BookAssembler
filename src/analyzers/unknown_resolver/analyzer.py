"""unknown_resolver: The pipeline's final default for unclassified text.

Every classification analyzer had a chance to claim an UnknownBlock and turn
it into something more specific (HeadingBlock, CaptionBlock, TableBlock, a
ListBlock item, ...). Whatever is still an UnknownBlock by the time this
runs was not claimed by anything — the honest default is that it is ordinary
prose, so it becomes a ParagraphBlock (RFC 0002 §2, UnknownBlock).

This must run after every classification analyzer and before anything that
only understands ParagraphBlock (assemblers, the chunker, ReadingOrderAnalyzer).
"""

from typing import Any, Dict, Optional

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock, UnknownBlock


class UnknownResolverAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="UnknownResolverAnalyzer",
                version="1.0.0",
                description="Resolves unclaimed UnknownBlock nodes to ParagraphBlock",
                krm_permissions={KRMPermission.READ, KRMPermission.TRANSFORM_NODE},
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=[],
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
        for child in list(container.children):
            if isinstance(child, ContainerUnit):
                self._process_container(child)

        replacements: Dict[int, ParagraphBlock] = {}
        for idx, child in enumerate(container.children):
            if not isinstance(child, UnknownBlock) or child.is_tombstoned:
                continue
            resolved = ParagraphBlock(
                inlines=child.inlines,
                parent_container_id=child.parent_container_id,
                provenance_info=child.provenance_info,
                visual_layout=child.visual_layout,
                metadata=child.metadata,
                extraction_confidence=child.extraction_confidence,
                classification_confidence=child.classification_confidence,
                confidence_score=child.confidence_score,
            )
            resolved.id = child.id  # RFC 0001 §2.3: reclassification keeps identity
            replacements[idx] = resolved

        if not replacements:
            return
        for idx, resolved in replacements.items():
            container.children[idx] = resolved
