"""proper_noun: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import block_text
from typing import Any, Dict, List, Optional, Set, Tuple
from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import (
    EntityType,
    KGEntityNode,
    KnowledgeGraph,
    RelationType,
)
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

from src.analyzers.proper_noun.signals import _PATTERNS

class ProperNounExtractorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="ProperNounExtractorAnalyzer",
                version="1.0.0",
                description="Extract Person/Organization/Product/Date/Version entities via regex",
                krm_permissions={KRMPermission.READ},
                rg_permissions=set(),
                kg_permissions={
                    KGPermission.READ,
                    KGPermission.MUTATE_ENTITIES,
                    KGPermission.MUTATE_EDGES,
                },
                depends_on=["NormalizationAnalyzer", "HeadingAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        seen: Dict[str, str] = {}  # canonical_name → entity_id
        for root in doc.root_containers:
            self._process(root, kg, seen)

    def _process(
        self,
        container: ContainerUnit,
        kg: KnowledgeGraph,
        seen: Dict[str, str],
    ) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child, kg, seen)
                continue
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                continue

            text = block_text(child)
            if not text:
                continue

            for pattern, etype in _PATTERNS:
                for m in pattern.finditer(text):
                    name = m.group(0).strip()
                    canonical = name.lower()
                    if canonical in seen:
                        eid = seen[canonical]
                    else:
                        entity = KGEntityNode(
                            name=name,
                            entity_type=etype,
                            canonical_name=canonical,
                        )
                        kg.add_entity(entity)
                        seen[canonical] = entity.id
                        eid = entity.id

                    kg.add_edge(
                        source_id=child.id,
                        target_id=eid,
                        relation_type=RelationType.MENTIONS_ENTITY,
                        confidence=0.8,
                        analyzer_name="ProperNounExtractorAnalyzer",
                    )
