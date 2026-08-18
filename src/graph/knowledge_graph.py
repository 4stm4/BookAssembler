"""
Knowledge Graph (KG) implementation for Knowledge Assembly Engine (KAE).

This module defines entity nodes, semantic edge relations, and the multi-graph
container for representing domain entities, cross-references, and concepts
according to RFC 0003 (docs/architecture/0003-knowledge-graph.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Complete isolation from KRM internal structures (references by node ID strings)
- Multi-graph support with idempotency for duplicate edge registrations
- Standard library dependencies only (dataclasses, enum, typing, uuid, json)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4


class EntityType(str, Enum):
    """
    Types of semantic domain entities represented in the Knowledge Graph.
    """
    HARDWARE_COMPONENT = "hardware_component"
    REGISTER = "register"
    INSTRUCTION = "instruction"
    FLAG = "flag"
    CONCEPT_TERM = "concept_term"
    SOFTWARE_API = "software_api"
    BIBLIOGRAPHY_CITE = "bibliography_cite"


@dataclass
class KGEntityNode:
    """
    Named entity or domain concept stored within the Knowledge Graph.
    """
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    entity_type: EntityType = EntityType.CONCEPT_TERM
    canonical_name: Optional[str] = None
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class RelationType(str, Enum):
    """
    Semantic relation types between KRM nodes and KG entities.
    """
    REFERENCES = "references"
    CAPTION_FOR = "caption_for"
    FOOTNOTE_FOR = "footnote_for"
    CONTINUATION_OF = "continuation_of"
    DEFINES_ENTITY = "defines_entity"
    MENTIONS_ENTITY = "mentions_entity"
    CONCRETIZES = "concretizes"
    EXEMPLIFIES = "exemplifies"
    USES_REGISTER = "uses_register"
    AFFECTS_FLAG = "affects_flag"
    PART_OF_ARCHITECTURE = "part_of_arch"


@dataclass
class KGEdge:
    """
    Directed semantic edge connecting two nodes/entities in the Knowledge Graph.
    """
    source_id: str
    target_id: str
    relation_type: RelationType
    confidence: float = 1.0
    provenance_analyzer: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class KnowledgeGraph:
    """
    Multi-graph container managing semantic entities and directed relation edges.
    Isolated from KRM nodes, connecting KRM node IDs and KG Entity IDs.
    """

    def __init__(self) -> None:
        self._entities: Dict[str, KGEntityNode] = {}
        self._edges: List[KGEdge] = []
        # Key: (source_id, target_id, relation_type, provenance_analyzer) -> index in _edges
        self._edge_index: Dict[Tuple[str, str, RelationType, str], int] = {}
        self._adjacency_out: Dict[str, List[KGEdge]] = {}
        self._adjacency_in: Dict[str, List[KGEdge]] = {}

    def add_entity(self, entity: KGEntityNode) -> None:
        """
        Adds or updates a domain entity node in the Knowledge Graph.
        """
        self._entities[entity.id] = entity

    def get_entity(self, entity_id: str) -> Optional[KGEntityNode]:
        """
        Retrieves an entity node by its ID.
        """
        return self._entities.get(entity_id)

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        confidence: float = 1.0,
        analyzer_name: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Adds a directed semantic edge between two IDs.
        If an edge with identical (source_id, target_id, relation_type, analyzer_name) exists,
        its confidence score and metadata are updated idempotently without duplicating the edge.
        """
        edge_metadata = metadata if metadata is not None else {}
        lookup_key = (source_id, target_id, relation_type, analyzer_name)

        if lookup_key in self._edge_index:
            existing_idx = self._edge_index[lookup_key]
            existing_edge = self._edges[existing_idx]
            existing_edge.confidence = confidence
            if edge_metadata:
                existing_edge.metadata.update(edge_metadata)
            return

        edge = KGEdge(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            confidence=confidence,
            provenance_analyzer=analyzer_name,
            metadata=edge_metadata,
        )

        idx = len(self._edges)
        self._edges.append(edge)
        self._edge_index[lookup_key] = idx

        self._adjacency_out.setdefault(source_id, []).append(edge)
        self._adjacency_in.setdefault(target_id, []).append(edge)

    def get_outgoing_edges(
        self, node_id: str, relation_type: Optional[RelationType] = None
    ) -> List[KGEdge]:
        """
        Retrieves all outgoing edges from a given source node ID, optionally filtered by relation_type.
        """
        edges = self._adjacency_out.get(node_id, [])
        if relation_type is None:
            return list(edges)
        return [e for e in edges if e.relation_type == relation_type]

    def get_incoming_edges(
        self, node_id: str, relation_type: Optional[RelationType] = None
    ) -> List[KGEdge]:
        """
        Retrieves all incoming edges to a given target node ID, optionally filtered by relation_type.
        """
        edges = self._adjacency_in.get(node_id, [])
        if relation_type is None:
            return list(edges)
        return [e for e in edges if e.relation_type == relation_type]

    def validate_integrity(self, krm_node_ids: Set[str]) -> List[str]:
        """
        RFC 0003 §5.1 (No Dangling Edges): every edge endpoint must resolve to an
        existing KRM node id or a registered KG entity. Returns a list of human-
        readable violation descriptions (empty if the graph is consistent).
        """
        known = set(krm_node_ids) | set(self._entities.keys())
        violations: List[str] = []
        for edge in self._edges:
            if edge.source_id not in known:
                violations.append(
                    f"dangling source '{edge.source_id}' ({edge.relation_type.value})"
                )
            if edge.target_id not in known:
                violations.append(
                    f"dangling target '{edge.target_id}' ({edge.relation_type.value})"
                )
        return violations

    def to_json_dict(self) -> Dict[str, Any]:
        """
        Serializes the Knowledge Graph into a dictionary compliant with KAE-KG JSON Schema.
        """
        entities_list: List[Dict[str, Any]] = [
            {
                "id": ent.id,
                "name": ent.name,
                "entity_type": ent.entity_type.value,
                "canonical_name": ent.canonical_name,
                "description": ent.description,
                "metadata": ent.metadata,
            }
            for ent in self._entities.values()
        ]

        edges_list: List[Dict[str, Any]] = [
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "relation_type": edge.relation_type.value,
                "confidence": edge.confidence,
                "provenance_analyzer": edge.provenance_analyzer,
                "metadata": edge.metadata,
            }
            for edge in self._edges
        ]

        return {
            "graph_version": "1.0.0",
            "entities": entities_list,
            "edges": edges_list,
        }
