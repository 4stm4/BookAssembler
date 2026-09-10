"""Mutation Delta validation and application tests (RFC 0010 §5, §6.3)."""

import pytest

from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock
from src.plugins.manifest import PluginPermissions
from src.plugins.mutations import MutationDelta, MutationRejectedError


def _document() -> KnowledgeDocument:
    paragraph = ParagraphBlock()
    chapter = ContainerUnit(title="Chapter 1", level=1, children=[paragraph])
    return KnowledgeDocument(title="Doc", root_containers=[chapter])


def _permissions(**overrides) -> PluginPermissions:
    return PluginPermissions(
        krm_permissions=overrides.get("krm", ["READ"]),
        rg_permissions=overrides.get("rg", ["READ"]),
        kg_permissions=overrides.get("kg", ["READ", "MUTATE_ENTITIES", "MUTATE_EDGES"]),
    )


def _entity_op(entity_id: str = "ent_01") -> dict:
    return {
        "op": "add_kg_entity",
        "entity": {"id": entity_id, "name": "Benzene", "entity_type": "concept_term"},
    }


def test_permitted_delta_applies() -> None:
    doc, rg, kg = _document(), ReadingGraph(), KnowledgeGraph()
    delta = MutationDelta.from_dict(
        {
            "plugin_id": "plugin.org.chem",
            "applied_mutations": [
                _entity_op(),
                {
                    "op": "add_kg_edge",
                    "edge": {
                        "source_id": "block_45a",
                        "target_id": "ent_01",
                        "relation_type": "mentions_entity",
                        "confidence": 0.99,
                    },
                },
            ],
        }
    )

    assert delta.apply(doc, rg, kg, _permissions()) == 2
    assert kg.get_entity("ent_01") is not None
    assert len(kg.get_outgoing_edges("block_45a")) == 1


def test_unpermitted_op_rejects_whole_delta() -> None:
    """A permitted op preceding a forbidden one must not be applied (RFC 0010 §6.3)."""
    doc, rg, kg = _document(), ReadingGraph(), KnowledgeGraph()
    delta = MutationDelta.from_dict(
        {
            "plugin_id": "plugin.org.rogue",
            "applied_mutations": [
                _entity_op(),
                {"op": "tombstone_krm_node", "node_id": doc.root_containers[0].id},
            ],
        }
    )

    with pytest.raises(MutationRejectedError, match="TOMBSTONE"):
        delta.apply(doc, rg, kg, _permissions())

    assert kg.get_entity("ent_01") is None
    assert doc.root_containers[0].is_tombstoned is False


def test_tombstone_applies_when_granted() -> None:
    doc, rg, kg = _document(), ReadingGraph(), KnowledgeGraph()
    target = doc.root_containers[0].children[0]
    delta = MutationDelta.from_dict(
        {"applied_mutations": [{"op": "tombstone_krm_node", "node_id": target.id}]}
    )

    delta.apply(doc, rg, kg, _permissions(krm=["READ", "TOMBSTONE"]))

    assert target.is_tombstoned is True


def test_unknown_op_is_rejected() -> None:
    with pytest.raises(MutationRejectedError, match="Unknown mutation op"):
        MutationDelta.from_dict(
            {"applied_mutations": [{"op": "delete_krm_node", "node_id": "x"}]}
        )


def test_malformed_payload_rejects_before_applying() -> None:
    doc, rg, kg = _document(), ReadingGraph(), KnowledgeGraph()
    delta = MutationDelta.from_dict(
        {
            "applied_mutations": [
                _entity_op(),
                {"op": "add_kg_entity", "entity": {"id": "ent_02"}},
            ]
        }
    )

    with pytest.raises(MutationRejectedError, match="Malformed payload"):
        delta.apply(doc, rg, kg, _permissions())

    assert kg.get_entity("ent_01") is None


def test_tombstone_of_unknown_node_is_rejected() -> None:
    doc, rg, kg = _document(), ReadingGraph(), KnowledgeGraph()
    delta = MutationDelta.from_dict(
        {"applied_mutations": [{"op": "tombstone_krm_node", "node_id": "nope"}]}
    )

    with pytest.raises(MutationRejectedError, match="unknown node"):
        delta.apply(doc, rg, kg, _permissions(krm=["READ", "TOMBSTONE"]))
