"""entity: The analyzer itself: orchestration and KRM writes."""

from typing import Any, Dict, List, Optional
from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import EntityType, KGEntityNode, KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    BaseKRMNode,
    ContainerUnit,
    InlineUnit,
    KnowledgeDocument,
    ParagraphBlock,
    SpanUnit,
    TableBlock,
)

from src.analyzers.entity.signals import _PATTERNS
from src.analyzers.entity.rules import _collect_spans

class EntityExtractorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="EntityExtractorAnalyzer",
                version="1.0.0",
                description="Extracts hardware entities via regex patterns",
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
        entity_cache: Dict[str, KGEntityNode] = {}

        for span in _collect_spans(doc):
            if not span.text:
                continue

            mentions: List[Dict[str, Any]] = []

            for pattern, entity_type in _PATTERNS:
                for match in pattern.finditer(span.text):
                    name = match.group(0)
                    canonical = name.upper()
                    cache_key = f"{entity_type.value}:{canonical}"

                    if cache_key not in entity_cache:
                        entity = KGEntityNode(
                            name=name,
                            entity_type=entity_type,
                            canonical_name=canonical,
                        )
                        entity_cache[cache_key] = entity
                        kg.add_entity(entity)

                    entity = entity_cache[cache_key]
                    mentions.append({
                        "entity_id": entity.id,
                        "entity_type": entity_type.value,
                        "start": match.start(),
                        "end": match.end(),
                        "text": name,
                    })

                    kg.add_edge(
                        span.id,
                        entity.id,
                        RelationType.MENTIONS_ENTITY,
                        confidence=0.95,
                        analyzer_name=self.manifest.name,
                    )

            if mentions:
                span.metadata["entity_mentions"] = mentions
