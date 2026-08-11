import re
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

_REGISTER_RE = re.compile(r"\b(R1[0-5]|R[0-9])\b")
_INSTRUCTION_RE = re.compile(
    r"\b(MOV|ADD|SUB|MUL|DIV|LDR|STR|CMP|BNE|BEQ|BGT|BLT|BGE|BLE|"
    r"AND|ORR|EOR|LSL|LSR|ASR|NOP|SWI|SVC|BL|BX|PUSH|POP|LDM|STM)\b"
)
_HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]{2,}\b")

_PATTERNS = [
    (_REGISTER_RE, EntityType.REGISTER),
    (_INSTRUCTION_RE, EntityType.INSTRUCTION),
    (_HEX_RE, EntityType.CONCEPT_TERM),
]


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


def _collect_spans(doc: KnowledgeDocument) -> List[SpanUnit]:
    spans: List[SpanUnit] = []

    def _walk(node: BaseKRMNode) -> None:
        if isinstance(node, SpanUnit):
            spans.append(node)
        elif isinstance(node, ContainerUnit):
            for child in node.children:
                _walk(child)
        elif isinstance(node, ParagraphBlock):
            for inline in node.inlines:
                _walk(inline)
        elif isinstance(node, InlineUnit):
            for s in node.spans:
                _walk(s)
        elif isinstance(node, TableBlock):
            for row in node.grid:
                for cell in row:
                    for content_node in cell.content:
                        _walk(content_node)

    for container in doc.root_containers:
        _walk(container)
    return spans
