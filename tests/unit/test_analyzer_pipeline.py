"""
Unit tests for Analyzer API and PipelineRunner execution engine.

Tests verify:
1. ValueError raised when pipeline dependency ordering is invalid (depends_on).
2. Successful sequential execution of valid analyzers.
3. Provenance info updated with analyzer names upon successful execution.
4. SecurityViolationError raised when an analyzer attempts unauthorized operations.
"""

from typing import Any, Dict, Optional
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


from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
    RGPermission,
    SecurityViolationError,
)
from src.analyzers.pipeline import PipelineRunner
from src.graph.knowledge_graph import (
    EntityType,
    KGEntityNode,
    KnowledgeGraph,
    RelationType,
)
from src.graph.reading_graph import ReadingGraph, ReadingTrack
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock, StyledTextSpan, TextLineInline


# Dummy test analyzers for testing pipeline and permissions

class MockLayoutAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        manifest = AnalyzerManifest(
            name="LayoutAnalyzer",
            version="1.0.0",
            description="Extracts basic document layout.",
            krm_permissions={KRMPermission.READ, KRMPermission.MUTATE_ATTRIBUTES},
            rg_permissions={RGPermission.READ, RGPermission.MUTATE_EDGES},
            kg_permissions={KGPermission.READ},
            depends_on=[],
        )
        super().__init__(manifest)

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        doc.title = "Analyzed Document Title"
        if doc.root_containers and doc.root_containers[0].children:
            child = doc.root_containers[0].children[0]
            rg.add_step("root", child.id, track=ReadingTrack.MAIN_FLOW)


class MockEntityAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        manifest = AnalyzerManifest(
            name="EntityAnalyzer",
            version="1.0.0",
            description="Extracts registers and hardware entities.",
            krm_permissions={KRMPermission.READ},
            rg_permissions={RGPermission.READ},
            kg_permissions={KGPermission.READ, KGPermission.MUTATE_ENTITIES, KGPermission.MUTATE_EDGES},
            depends_on=["LayoutAnalyzer"],
        )
        super().__init__(manifest)

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        ent = KGEntityNode(
            name="AX",
            entity_type=EntityType.REGISTER,
            canonical_name="AX",
        )
        kg.add_entity(ent)
        kg.add_edge(
            source_id=doc.id,
            target_id=ent.id,
            relation_type=RelationType.MENTIONS_ENTITY,
            confidence=0.95,
            analyzer_name=self.manifest.name,
        )


class UnauthorizedMutatingAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        manifest = AnalyzerManifest(
            name="RogueAnalyzer",
            version="1.0.0",
            description="Attempts unauthorized mutation without permissions.",
            krm_permissions={KRMPermission.READ},  # Lacks MUTATE_ATTRIBUTES
            rg_permissions={RGPermission.READ},
            kg_permissions={KGPermission.READ},
            depends_on=[],
        )
        super().__init__(manifest)

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Should fail: lacks MUTATE_ATTRIBUTES
        doc.title = "Hacked Title"


class UnauthorizedReadingGraphAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        manifest = AnalyzerManifest(
            name="RogueRGAnalyzer",
            version="1.0.0",
            description="Attempts to add reading step without MUTATE_EDGES.",
            krm_permissions={KRMPermission.READ},
            rg_permissions={RGPermission.READ},  # Lacks MUTATE_EDGES
            kg_permissions={KGPermission.READ},
            depends_on=[],
        )
        super().__init__(manifest)

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Should fail: lacks MUTATE_EDGES
        rg.add_step("node1", "node2")


def test_dependency_resolution_missing_dependency() -> None:
    """Verify ValueError is raised when an analyzer depends on a missing preceding analyzer."""
    entity_analyzer = MockEntityAnalyzer()  # depends on LayoutAnalyzer

    # LayoutAnalyzer is missing
    with pytest.raises(ValueError, match="depends on 'LayoutAnalyzer'"):
        PipelineRunner([entity_analyzer])


def test_dependency_resolution_incorrect_order() -> None:
    """Verify ValueError is raised when analyzers are listed in wrong dependency order."""
    layout_analyzer = MockLayoutAnalyzer()
    entity_analyzer = MockEntityAnalyzer()

    # EntityAnalyzer comes before LayoutAnalyzer
    with pytest.raises(ValueError, match="placed after 'EntityAnalyzer'"):
        PipelineRunner([entity_analyzer, layout_analyzer])


def test_successful_pipeline_execution_and_provenance() -> None:
    """Verify valid pipeline execution updates documents, graphs, and provenance_info."""
    layout = MockLayoutAnalyzer()
    entity = MockEntityAnalyzer()

    runner = PipelineRunner([layout, entity])

    # Construct test document
    doc = KnowledgeDocument(title="Original Title")
    chapter = ContainerUnit(title="Chapter 1")
    para = ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text="Hello world")])]
    )
    chapter.children.append(para)
    doc.root_containers.append(chapter)

    rg = ReadingGraph()
    kg = KnowledgeGraph()

    runner.execute(doc, rg, kg)

    # Check that layout analyzer modified title
    assert doc.title == "Analyzed Document Title"

    # Check reading step added
    steps = rg.get_outgoing_edges("root")
    assert len(steps) == 1
    assert steps[0].target_id == para.id

    # Check KG entity added
    assert len(kg.to_json_dict()["entities"]) == 1
    assert kg.to_json_dict()["entities"][0]["name"] == "AX"

    # Verify provenance logging
    assert doc.provenance_info is not None
    assert "LayoutAnalyzer" in doc.provenance_info.applied_analyzers
    assert "EntityAnalyzer" in doc.provenance_info.applied_analyzers

    assert chapter.provenance_info is not None
    assert "LayoutAnalyzer" in chapter.provenance_info.applied_analyzers
    assert "EntityAnalyzer" in chapter.provenance_info.applied_analyzers

    assert para.provenance_info is not None
    assert "LayoutAnalyzer" in para.provenance_info.applied_analyzers
    assert "EntityAnalyzer" in para.provenance_info.applied_analyzers


def test_security_violation_krm_mutation() -> None:
    """Verify SecurityViolationError is raised on unauthorized KRM attribute mutation."""
    rogue = UnauthorizedMutatingAnalyzer()
    runner = PipelineRunner([rogue])

    doc = KnowledgeDocument(title="Original")
    rg = ReadingGraph()
    kg = KnowledgeGraph()

    with pytest.raises(SecurityViolationError, match="MUTATE_ATTRIBUTES"):
        runner.execute(doc, rg, kg)


def test_security_violation_rg_mutation() -> None:
    """Verify SecurityViolationError is raised on unauthorized ReadingGraph mutation."""
    rogue = UnauthorizedReadingGraphAnalyzer()
    runner = PipelineRunner([rogue])

    doc = KnowledgeDocument(title="Original")
    rg = ReadingGraph()
    kg = KnowledgeGraph()

    with pytest.raises(SecurityViolationError, match="MUTATE_EDGES"):
        runner.execute(doc, rg, kg)
