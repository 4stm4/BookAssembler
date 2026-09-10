"""Mutation Delta protocol for sandboxed plugins (RFC 0010 §5).

A sandboxed plugin never touches KRM/RG/KG objects: it returns a list of atomic
operations that the core validates against the plugin manifest before applying.
A single unauthorized or malformed operation rejects the whole delta — nothing is
applied (RFC 0010 §6.3).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from src.analyzers.base import KGPermission, KRMPermission, RGPermission
from src.analyzers.pipeline import GuardedKnowledgeGraph, GuardedReadingGraph
from src.graph.knowledge_graph import EntityType, KGEntityNode, KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph, ReadingTrack
from src.krm.models import KnowledgeDocument
from src.krm.traversal import walk as walk_krm
from src.plugins.api import _KG_PERM_MAP, _KRM_PERM_MAP, _RG_PERM_MAP
from src.plugins.manifest import PluginPermissions


class MutationRejectedError(Exception):
    """Raised when a plugin's Mutation Delta violates permissions or is malformed."""


_OP_PERMISSIONS: Dict[str, Tuple[str, Any]] = {
    "add_kg_entity": ("kg", KGPermission.MUTATE_ENTITIES),
    "add_kg_edge": ("kg", KGPermission.MUTATE_EDGES),
    "add_rg_step": ("rg", RGPermission.MUTATE_EDGES),
    "tombstone_krm_node": ("krm", KRMPermission.TOMBSTONE),
}


@dataclass(frozen=True)
class Mutation:
    op: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class MutationDelta:
    plugin_id: str = ""
    mutations: List[Mutation] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Any) -> "MutationDelta":
        if not isinstance(raw, dict):
            raise MutationRejectedError("Mutation Delta must be a JSON object")
        applied = raw.get("applied_mutations", [])
        if not isinstance(applied, list):
            raise MutationRejectedError("'applied_mutations' must be a list")

        mutations: List[Mutation] = []
        for item in applied:
            if not isinstance(item, dict):
                raise MutationRejectedError("Each mutation must be a JSON object")
            op = item.get("op")
            if op not in _OP_PERMISSIONS:
                raise MutationRejectedError(f"Unknown mutation op: {op!r}")
            mutations.append(
                Mutation(op=str(op), payload={k: v for k, v in item.items() if k != "op"})
            )
        return cls(plugin_id=str(raw.get("plugin_id", "")), mutations=mutations)

    def validate(self, doc: KnowledgeDocument, permissions: PluginPermissions) -> None:
        """Raise MutationRejectedError unless every operation is permitted and well-formed."""
        self._prepare(doc, permissions)

    def apply(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        permissions: PluginPermissions,
    ) -> int:
        """Validate the whole delta, then apply it. Returns the number of operations applied."""
        prepared = self._prepare(doc, permissions)
        granted = _granted_sets(permissions)
        guarded_rg = GuardedReadingGraph(rg, granted["rg"])
        guarded_kg = GuardedKnowledgeGraph(kg, granted["kg"])

        for op, obj in prepared:
            if op == "add_kg_entity":
                guarded_kg.add_entity(obj)
            elif op == "add_kg_edge":
                source_id, target_id, relation, confidence = obj
                guarded_kg.add_edge(
                    source_id, target_id, relation, confidence, self.plugin_id
                )
            elif op == "add_rg_step":
                source_id, target_id, track, confidence = obj
                guarded_rg.add_step(
                    source_id, target_id, track, confidence, self.plugin_id
                )
            elif op == "tombstone_krm_node":
                obj.is_tombstoned = True
        return len(prepared)

    def _prepare(
        self, doc: KnowledgeDocument, permissions: PluginPermissions
    ) -> List[Tuple[str, Any]]:
        """Check permissions and payload shape for every operation before any is applied."""
        granted = _granted_sets(permissions)
        prepared: List[Tuple[str, Any]] = []

        for mutation in self.mutations:
            domain, required = _OP_PERMISSIONS[mutation.op]
            if required not in granted[domain]:
                raise MutationRejectedError(
                    f"Plugin {self.plugin_id!r} lacks {domain.upper()} permission "
                    f"{required.name} required by op {mutation.op!r}; delta rejected"
                )
            prepared.append((mutation.op, _build(mutation, doc)))
        return prepared


def _granted_sets(permissions: PluginPermissions) -> Dict[str, Set[Any]]:
    return {
        "krm": {
            _KRM_PERM_MAP[p] for p in permissions.krm_permissions if p in _KRM_PERM_MAP
        },
        "rg": {_RG_PERM_MAP[p] for p in permissions.rg_permissions if p in _RG_PERM_MAP},
        "kg": {_KG_PERM_MAP[p] for p in permissions.kg_permissions if p in _KG_PERM_MAP},
    }


def _build(mutation: Mutation, doc: KnowledgeDocument) -> Any:
    try:
        if mutation.op == "add_kg_entity":
            entity = mutation.payload["entity"]
            return KGEntityNode(
                id=str(entity["id"]),
                name=str(entity.get("name", "")),
                entity_type=EntityType(entity["entity_type"]),
            )

        if mutation.op == "add_kg_edge":
            edge = mutation.payload["edge"]
            return (
                str(edge["source_id"]),
                str(edge["target_id"]),
                RelationType(edge["relation_type"]),
                float(edge.get("confidence", 1.0)),
            )

        if mutation.op == "add_rg_step":
            step = mutation.payload["step"]
            return (
                str(step["source_id"]),
                str(step["target_id"]),
                ReadingTrack(step.get("track", ReadingTrack.MAIN_FLOW.value)),
                float(step.get("confidence", 1.0)),
            )

        node_id = str(mutation.payload["node_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MutationRejectedError(
            f"Malformed payload for op {mutation.op!r}: {exc}"
        ) from exc

    for node in walk_krm(doc):
        if getattr(node, "id", None) == node_id:
            return node
    raise MutationRejectedError(
        f"op 'tombstone_krm_node' targets unknown node {node_id!r}"
    )
