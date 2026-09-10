"""Tests for Plugin API guarded proxy (RFC 0010 §4, RFC 0005 §5)."""
import pytest

from src.analyzers.base import SecurityViolationError
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import ContainerUnit, KnowledgeDocument
from src.plugins.api import PluginAPI
from src.plugins.manifest import PluginPermissions


def _make_api(krm_perms=None, kg_perms=None):
    doc = KnowledgeDocument(
        title="Test Doc",
        root_containers=[ContainerUnit(title="Ch1", level=1)],
    )
    rg = ReadingGraph()
    kg = KnowledgeGraph()
    perms = PluginPermissions(
        krm_permissions=krm_perms or [],
        kg_permissions=kg_perms or [],
    )
    return PluginAPI(doc, rg, kg, perms), kg


class TestReadPermissions:
    def test_read_title(self):
        api, _ = _make_api(krm_perms=["READ"])
        assert api.get_document_title() == "Test Doc"

    def test_read_denied(self):
        api, _ = _make_api()
        with pytest.raises(SecurityViolationError):
            api.get_document_title()

    def test_get_container_ids(self):
        api, _ = _make_api(krm_perms=["READ"])
        ids = api.get_root_container_ids()
        assert len(ids) == 1


class TestKGPermissions:
    def test_read_entities(self):
        api, _ = _make_api(kg_perms=["READ"])
        assert api.get_entity_names() == []

    def test_add_entity_denied(self):
        api, _ = _make_api(kg_perms=["READ"])
        with pytest.raises(SecurityViolationError):
            api.add_entity("e1", "Test", "concept_term")

    def test_add_entity_allowed(self):
        api, kg = _make_api(kg_perms=["READ", "MUTATE_ENTITIES"])
        api.add_entity("e1", "Benzene", "concept_term")
        assert len(kg._entities) == 1

    def test_add_edge_denied(self):
        api, _ = _make_api(kg_perms=["READ"])
        with pytest.raises(SecurityViolationError):
            api.add_edge("a", "b", "mentions_entity")

    def test_add_edge_allowed(self):
        api, kg = _make_api(kg_perms=["MUTATE_EDGES"])
        api.add_edge("a", "b", "mentions_entity", 0.9)
        edges = kg.get_outgoing_edges("a")
        assert len(edges) == 1
