"""
Unit tests for Knowledge Graph (KG) and Reading Graph (RG) invariants.

Tests verify:
1. CyclicReadingPathError prevention when attempting A -> B -> C -> A cycle in ReadingGraph.
2. Correct linear sequence retrieval via get_sequence() in ReadingGraph.
3. Idempotency of edge registration in KnowledgeGraph (updates confidence and metadata without duplicating).
4. KnowledgeGraph.to_json_dict() serialization adhering to KAE-KG JSON Schema.
5. Edge retrieval and filtering functions across both graphs.
"""

from typing import Any
import contextlib
import re

try:
    import pytest
except ImportError:
    @contextlib.contextmanager
    def _pytest_raises_fallback(expected_exception: type[BaseException], match: str | None = None) -> Any:
        try:
            yield
        except expected_exception as e:
            if match and not re.search(match, str(e)):
                raise AssertionError(f"Pattern '{match}' not found in exception message: '{e}'")
        else:
            raise AssertionError(f"Expected exception {expected_exception} was not raised")

    class _PytestShim:
        raises = staticmethod(_pytest_raises_fallback)

    pytest = _PytestShim()  # type: ignore[assignment]


from src.graph.knowledge_graph import (
    EntityType,
    KGEntityNode,
    KnowledgeGraph,
    RelationType,
)
from src.graph.reading_graph import (
    CyclicReadingPathError,
    ReadingGraph,
    ReadingTrack,
)


def test_reading_graph_cycle_prevention() -> None:
    """Verify that adding an edge closing a cycle (A -> B -> C -> A) raises CyclicReadingPathError."""
    rg = ReadingGraph()

    # Build chain: node_A -> node_B -> node_C
    rg.add_step("node_A", "node_B", track=ReadingTrack.MAIN_FLOW)
    rg.add_step("node_B", "node_C", track=ReadingTrack.MAIN_FLOW)

    # Attempting to add node_C -> node_A must raise CyclicReadingPathError
    with pytest.raises(CyclicReadingPathError, match="creates a cycle"):
        rg.add_step("node_C", "node_A", track=ReadingTrack.MAIN_FLOW)

    # Self-loop node_A -> node_A must also raise CyclicReadingPathError
    with pytest.raises(CyclicReadingPathError, match="creates a cycle"):
        rg.add_step("node_A", "node_A", track=ReadingTrack.MAIN_FLOW)


def test_reading_graph_sequence_traversal() -> None:
    """Verify linear sequence traversal via get_sequence()."""
    rg = ReadingGraph()

    rg.add_step("block_01", "block_02", track=ReadingTrack.MAIN_FLOW, confidence=0.9)
    rg.add_step("block_02", "block_03", track=ReadingTrack.MAIN_FLOW, confidence=0.95)
    rg.add_step("block_03", "block_04", track=ReadingTrack.MAIN_FLOW, confidence=0.99)

    # Add a sidebar step branching from block_02
    rg.add_step("block_02", "sidebar_01", track=ReadingTrack.SIDEBAR_FLOW, confidence=1.0)

    # Main flow sequence starting from block_01
    main_seq = rg.get_sequence("block_01", track=ReadingTrack.MAIN_FLOW)
    assert main_seq == ["block_01", "block_02", "block_03", "block_04"]

    # Sidebar flow sequence starting from block_02
    sidebar_seq = rg.get_sequence("block_02", track=ReadingTrack.SIDEBAR_FLOW)
    assert sidebar_seq == ["block_02", "sidebar_01"]


def test_knowledge_graph_edge_idempotency() -> None:
    """Verify edge idempotency in KnowledgeGraph when re-adding identical edge."""
    kg = KnowledgeGraph()

    ent = KGEntityNode(
        name="AX Register",
        entity_type=EntityType.REGISTER,
        canonical_name="AX",
    )
    kg.add_entity(ent)

    # Add edge from block_10 to ent.id
    kg.add_edge(
        source_id="block_10",
        target_id=ent.id,
        relation_type=RelationType.USES_REGISTER,
        confidence=0.8,
        analyzer_name="InstructionAnalyzer",
        metadata={"note": "first pass"},
    )

    out_edges_1 = kg.get_outgoing_edges("block_10")
    assert len(out_edges_1) == 1
    assert out_edges_1[0].confidence == 0.8
    assert out_edges_1[0].metadata["note"] == "first pass"

    # Re-add edge with updated confidence and metadata from same analyzer
    kg.add_edge(
        source_id="block_10",
        target_id=ent.id,
        relation_type=RelationType.USES_REGISTER,
        confidence=0.98,
        analyzer_name="InstructionAnalyzer",
        metadata={"note": "second pass updated", "verified": True},
    )

    out_edges_2 = kg.get_outgoing_edges("block_10")
    # Edge count must remain 1 (no duplicate)
    assert len(out_edges_2) == 1
    assert out_edges_2[0].confidence == 0.98
    assert out_edges_2[0].metadata["note"] == "second pass updated"
    assert out_edges_2[0].metadata["verified"] is True


def test_knowledge_graph_json_serialization() -> None:
    """Verify KnowledgeGraph serialization to dict compliant with KAE-KG JSON Schema."""
    kg = KnowledgeGraph()

    ent_ready = KGEntityNode(
        id="ent_ready_01",
        name="READY Signal",
        entity_type=EntityType.HARDWARE_COMPONENT,
        description="Hardware synchronization signal",
    )
    kg.add_entity(ent_ready)

    kg.add_edge(
        source_id="chk_1024",
        target_id="ent_ready_01",
        relation_type=RelationType.MENTIONS_ENTITY,
        confidence=0.95,
        analyzer_name="EntityMentionAnalyzer",
    )

    json_dict = kg.to_json_dict()

    assert json_dict["graph_version"] == "1.0.0"
    assert len(json_dict["entities"]) == 1
    assert json_dict["entities"][0]["id"] == "ent_ready_01"
    assert json_dict["entities"][0]["name"] == "READY Signal"
    assert json_dict["entities"][0]["entity_type"] == "hardware_component"

    assert len(json_dict["edges"]) == 1
    assert json_dict["edges"][0]["source_id"] == "chk_1024"
    assert json_dict["edges"][0]["target_id"] == "ent_ready_01"
    assert json_dict["edges"][0]["relation_type"] == "mentions_entity"
    assert json_dict["edges"][0]["confidence"] == 0.95
    assert json_dict["edges"][0]["provenance_analyzer"] == "EntityMentionAnalyzer"


def test_knowledge_graph_incoming_and_outgoing_filters() -> None:
    """Verify edge filtering by RelationType on incoming and outgoing edges."""
    kg = KnowledgeGraph()

    kg.add_edge("block_1", "block_2", RelationType.CONTINUATION_OF)
    kg.add_edge("block_1", "ent_1", RelationType.DEFINES_ENTITY)
    kg.add_edge("block_3", "ent_1", RelationType.MENTIONS_ENTITY)

    # Test outgoing edge filtering
    b1_all = kg.get_outgoing_edges("block_1")
    assert len(b1_all) == 2

    b1_defines = kg.get_outgoing_edges("block_1", RelationType.DEFINES_ENTITY)
    assert len(b1_defines) == 1
    assert b1_defines[0].target_id == "ent_1"

    # Test incoming edge filtering
    ent1_incoming_all = kg.get_incoming_edges("ent_1")
    assert len(ent1_incoming_all) == 2

    ent1_mentions = kg.get_incoming_edges("ent_1", RelationType.MENTIONS_ENTITY)
    assert len(ent1_mentions) == 1
    assert ent1_mentions[0].source_id == "block_3"
