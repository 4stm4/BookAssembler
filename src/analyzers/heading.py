from typing import Any, Dict, List, Optional

from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KGEntityNode, KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument
from src.graph.knowledge_graph import EntityType


class HeadingAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="HeadingAnalyzer",
                version="1.0.0",
                description="Validates heading hierarchy and creates continuation edges",
                krm_permissions={KRMPermission.READ, KRMPermission.MUTATE_ATTRIBUTES},
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
        containers: List[ContainerUnit] = []
        _collect_containers(doc.root_containers, containers)

        prev_level = 0
        prev_at_level: Dict[int, ContainerUnit] = {}

        for container in containers:
            # Validate level hierarchy
            if container.level > prev_level + 1 and prev_level > 0:
                container.confidence_score = 0.5
                container.metadata["heading_violation"] = True

            # Create KG entity for this heading
            entity = KGEntityNode(
                id=container.id,
                name=container.title or f"Section L{container.level}",
                entity_type=EntityType.CONCEPT_TERM,
            )
            kg.add_entity(entity)

            # CONTINUATION_OF edges between sequential containers at same level
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


def _collect_containers(
    containers: List[ContainerUnit], result: List[ContainerUnit]
) -> None:
    for c in containers:
        result.append(c)
        child_containers = [ch for ch in c.children if isinstance(ch, ContainerUnit)]
        if child_containers:
            _collect_containers(child_containers, result)
