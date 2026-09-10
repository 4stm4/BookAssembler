"""heading: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import block_text, font_size
from typing import Any, Dict, List, Optional
from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KGEntityNode, KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock
from src.graph.knowledge_graph import EntityType

from src.analyzers.heading.rules import _collect_containers, _detect_heading_threshold, _heading_level, _is_heading, _is_monospace

class HeadingAnalyzer(BaseAnalyzer):
    """
    Builds the heading hierarchy (RFC 0008 §5.2: this is analysis, not adapter work).
    Promotes large-font ParagraphBlocks to ContainerUnit headings and nests the
    intervening content, preserving node identity (RFC 0001 §2.3).
    """

    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="HeadingAnalyzer",
                version="2.0.0",
                description="Detects headings by typography and builds the container tree",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.INSERT,
                },
                rg_permissions=set(),
                kg_permissions={KGPermission.READ, KGPermission.MUTATE_ENTITIES, KGPermission.MUTATE_EDGES},
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
        # 1. Global body-font threshold across all ParagraphBlocks.
        sizes: List[float] = []
        for root in doc.root_containers:
            for blk in root.children:
                if isinstance(blk, ParagraphBlock) and not _is_monospace(blk):
                    sizes.append(font_size(blk, default=12.0))
        threshold = _detect_heading_threshold(sizes)

        # 2. Promote headings and build the container tree per root.
        for root in doc.root_containers:
            self._build_tree(root, threshold)

        # 3. Validate hierarchy + emit KG entities and CONTINUATION_OF edges.
        containers: List[ContainerUnit] = []
        _collect_containers(doc.root_containers, containers)

        prev_level = 0
        prev_at_level: Dict[int, ContainerUnit] = {}
        for container in containers:
            if container.level > prev_level + 1 and prev_level > 0:
                container.confidence_score = 0.5
                container.metadata["heading_violation"] = True

            entity = KGEntityNode(
                id=container.id,
                name=container.title or f"Section L{container.level}",
                entity_type=EntityType.CONCEPT_TERM,
            )
            kg.add_entity(entity)

            if container.level in prev_at_level:
                kg.add_edge(
                    prev_at_level[container.level].id,
                    container.id,
                    RelationType.CONTINUATION_OF,
                    confidence=1.0,
                    analyzer_name=self.manifest.name,
                )
            prev_at_level[container.level] = container
            prev_level = container.level

    def _build_tree(self, root: ContainerUnit, threshold: float) -> None:
        """Re-nest root's flat children into a heading hierarchy.

        Only restructures when the adapter delivered a flat block list. If the
        tree already contains nested ContainerUnits (idempotency / non-PDF
        sources), it is left untouched.
        """
        flat = list(root.children)
        if any(isinstance(c, ContainerUnit) for c in flat):
            return  # already structured

        root.children = []
        stack: List[ContainerUnit] = [root]

        for block in flat:
            if _is_heading(block, threshold):
                text = block_text(block)
                level = _heading_level(font_size(block, default=12.0), threshold)
                while len(stack) > 1 and stack[-1].level >= level:
                    stack.pop()

                heading = ContainerUnit(
                    title=text,
                    level=level,
                    visual_layout=block.visual_layout,
                    extraction_confidence=block.extraction_confidence,
                    classification_confidence=0.75,
                    confidence_score=min(block.extraction_confidence, 0.75),
                )
                heading.id = block.id  # RFC 0001 §2.3: identity preserved
                heading.provenance_info = block.provenance_info
                stack[-1].children.append(heading)
                stack.append(heading)
            else:
                stack[-1].children.append(block)
