"""Reading Graph and Knowledge Graph integrity invariants (RFC 0004 §5, RFC 0003 §5.1)."""

from src.graph.knowledge_graph import (
    EntityType,
    KGEntityNode,
    KnowledgeGraph,
    RelationType,
)
from src.graph.reading_graph import ReadingGraph, ReadingTrack


def _chain() -> ReadingGraph:
    rg = ReadingGraph()
    rg.add_step("a", "b")
    rg.add_step("b", "c")
    return rg


def test_single_chain_has_one_head() -> None:
    assert _chain().validate_invariants({"chapter": {"a", "b", "c"}}, {"a", "b", "c"}) == []


def test_two_chains_in_one_container_violate_single_head() -> None:
    rg = _chain()
    rg.add_step("d", "e")

    violations = rg.validate_invariants(
        {"chapter": {"a", "b", "c", "d", "e"}}, {"a", "b", "c", "d", "e"}
    )

    assert len(violations) == 1
    assert "2 disjoint starts" in violations[0]
    assert "main_flow" in violations[0]


def test_container_entered_from_the_previous_one_is_not_a_violation() -> None:
    """The main flow is one chain across the document: only the first container starts it."""
    rg = _chain()

    assert rg.validate_invariants(
        {"chapter_1": {"a"}, "chapter_2": {"b", "c"}}, {"a", "b", "c"}
    ) == []


def test_tracks_are_checked_independently() -> None:
    """A footnote chain alongside the main flow is not a second head."""
    rg = _chain()
    rg.add_step("f1", "f2", track=ReadingTrack.FOOTNOTE_FLOW)

    assert rg.validate_invariants(
        {"chapter": {"a", "b", "c", "f1", "f2"}}, {"a", "b", "c", "f1", "f2"}
    ) == []


def test_isolated_live_block_is_reported() -> None:
    violations = _chain().validate_invariants(
        {"chapter": {"a", "b", "c"}}, {"a", "b", "c", "orphan"}
    )

    assert len(violations) == 1
    assert "'orphan' is not part of any reading track" in violations[0]


def test_tombstoned_block_may_be_isolated() -> None:
    """Tombstoned nodes are excluded from live ids by the caller, so they never trip §5.3."""
    assert _chain().validate_invariants({"chapter": {"a", "b", "c"}}, {"a", "b", "c"}) == []


def test_containers_are_checked_separately() -> None:
    rg = _chain()
    rg.add_step("x", "y")

    assert rg.validate_invariants(
        {"chapter_1": {"a", "b", "c"}, "chapter_2": {"x", "y"}},
        {"a", "b", "c", "x", "y"},
    ) == []


def _kg_with_edge(source: str, target: str) -> KnowledgeGraph:
    kg = KnowledgeGraph()
    kg.add_entity(KGEntityNode(id="ent_1", name="R0", entity_type=EntityType.REGISTER))
    kg.add_edge(source, target, RelationType.MENTIONS_ENTITY)
    return kg


def test_dangling_edge_endpoint_is_reported() -> None:
    kg = _kg_with_edge("block_missing", "ent_1")

    violations = kg.validate_integrity({"block_present"})

    assert len(violations) == 1
    assert "block_missing" in violations[0]


def test_edge_between_known_nodes_is_clean() -> None:
    kg = _kg_with_edge("block_present", "ent_1")

    assert kg.validate_integrity({"block_present"}) == []
