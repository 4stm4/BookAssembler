"""Read-only Guarded API proxy for sandboxed plugins (RFC 0005 §5, RFC 0010 §4)."""

from typing import Any, Dict, List, Optional, Set

from src.analyzers.base import KGPermission, KRMPermission, RGPermission, SecurityViolationError
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import KnowledgeDocument
from src.plugins.manifest import PluginPermissions


_KRM_PERM_MAP = {
    "READ": KRMPermission.READ,
    "INSERT": KRMPermission.INSERT,
    "TRANSFORM_NODE": KRMPermission.TRANSFORM_NODE,
    "MUTATE_ATTRIBUTES": KRMPermission.MUTATE_ATTRIBUTES,
}

_KG_PERM_MAP = {
    "READ": KGPermission.READ,
    "MUTATE_ENTITIES": KGPermission.MUTATE_ENTITIES,
    "MUTATE_EDGES": KGPermission.MUTATE_EDGES,
}


class PluginAPI:
    """Guarded proxy exposing KRM/RG/KG to plugin code within declared permissions."""

    def __init__(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        permissions: PluginPermissions,
    ) -> None:
        self._doc = doc
        self._rg = rg
        self._kg = kg
        self._krm_perms: Set[KRMPermission] = set()
        for p in permissions.krm_permissions:
            if p in _KRM_PERM_MAP:
                self._krm_perms.add(_KRM_PERM_MAP[p])
        self._kg_perms: Set[KGPermission] = set()
        for p in permissions.kg_permissions:
            if p in _KG_PERM_MAP:
                self._kg_perms.add(_KG_PERM_MAP[p])

    def _require_krm(self, perm: KRMPermission) -> None:
        if perm not in self._krm_perms:
            raise SecurityViolationError(
                f"Plugin lacks KRM permission: {perm.value}"
            )

    def _require_kg(self, perm: KGPermission) -> None:
        if perm not in self._kg_perms:
            raise SecurityViolationError(
                f"Plugin lacks KG permission: {perm.value}"
            )

    def get_document_title(self) -> str:
        self._require_krm(KRMPermission.READ)
        return self._doc.title or ""

    def get_root_container_ids(self) -> List[str]:
        self._require_krm(KRMPermission.READ)
        return [c.id for c in self._doc.root_containers]

    def get_entity_names(self) -> List[str]:
        self._require_kg(KGPermission.READ)
        return [e.name for e in self._kg._entities.values()]

    def add_entity(self, entity_id: str, name: str, entity_type: str) -> None:
        self._require_kg(KGPermission.MUTATE_ENTITIES)
        from src.graph.knowledge_graph import KGEntityNode, EntityType
        et = EntityType(entity_type)
        self._kg.add_entity(KGEntityNode(id=entity_id, name=name, entity_type=et))

    def add_edge(
        self, source_id: str, target_id: str, relation_type: str, confidence: float = 1.0
    ) -> None:
        self._require_kg(KGPermission.MUTATE_EDGES)
        from src.graph.knowledge_graph import RelationType
        rt = RelationType(relation_type)
        self._kg.add_edge(source_id, target_id, rt, confidence)
