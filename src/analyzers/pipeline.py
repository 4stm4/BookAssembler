"""
Pipeline Execution Engine for Knowledge Assembly Engine (KAE).

This module implements PipelineRunner to execute analyzers sequentially with
strict permission enforcement and dependency resolution according to RFC 0005
(docs/architecture/0005-analyzer-api.md).

Guarantees:
- Strict dependency order checking (raises ValueError if dependencies are missing/misordered)
- Runtime security permission enforcement (raises SecurityViolationError)
- Automatic recording of provenance info (analyzer added to applied_analyzers)
- Strict typing (100% mypy --strict compatible)
"""

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from src.analyzers.base import (
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
    RGPermission,
    SecurityViolationError,
)
from src.graph.knowledge_graph import (
    KGEdge,
    KGEntityNode,
    KnowledgeGraph,
    RelationType,
)
from src.graph.reading_graph import (
    ReadingEdge,
    ReadingGraph,
    ReadingTrack,
)
from src.krm.models import (
    BaseKRMNode,
    CalloutBlock,
    ContainerUnit,
    InlineUnit,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    ParagraphBlock,
    ProvenanceInfo,
    SpanUnit,
    TableBlock,
    TableCell,
)


class GuardedReadingGraph(ReadingGraph):
    """
    Proxy wrapper around ReadingGraph that enforces RGPermission checks.
    """

    def __init__(self, target_rg: ReadingGraph, permissions: Set[RGPermission]) -> None:
        super().__init__()
        self._target = target_rg
        self._permissions = permissions

    def add_step(
        self,
        source_id: str,
        target_id: str,
        track: ReadingTrack = ReadingTrack.MAIN_FLOW,
        confidence: float = 1.0,
        analyzer_name: str = "",
    ) -> None:
        if RGPermission.MUTATE_EDGES not in self._permissions:
            raise SecurityViolationError(
                "Analyzer lacks RGPermission.MUTATE_EDGES permission to add_step."
            )
        self._target.add_step(source_id, target_id, track, confidence, analyzer_name)

    def get_outgoing_edges(
        self, node_id: str, track: Optional[ReadingTrack] = None
    ) -> List[ReadingEdge]:
        if RGPermission.READ not in self._permissions:
            raise SecurityViolationError("Analyzer lacks RGPermission.READ permission.")
        return self._target.get_outgoing_edges(node_id, track)

    def get_incoming_edges(
        self, node_id: str, track: Optional[ReadingTrack] = None
    ) -> List[ReadingEdge]:
        if RGPermission.READ not in self._permissions:
            raise SecurityViolationError("Analyzer lacks RGPermission.READ permission.")
        return self._target.get_incoming_edges(node_id, track)

    def get_sequence(
        self, root_id: str, track: ReadingTrack = ReadingTrack.MAIN_FLOW
    ) -> List[str]:
        if RGPermission.READ not in self._permissions:
            raise SecurityViolationError("Analyzer lacks RGPermission.READ permission.")
        return self._target.get_sequence(root_id, track)


class GuardedKnowledgeGraph(KnowledgeGraph):
    """
    Proxy wrapper around KnowledgeGraph that enforces KGPermission checks.
    """

    def __init__(self, target_kg: KnowledgeGraph, permissions: Set[KGPermission]) -> None:
        super().__init__()
        self._target = target_kg
        self._permissions = permissions

    def add_entity(self, entity: KGEntityNode) -> None:
        if KGPermission.MUTATE_ENTITIES not in self._permissions:
            raise SecurityViolationError(
                "Analyzer lacks KGPermission.MUTATE_ENTITIES permission to add_entity."
            )
        self._target.add_entity(entity)

    def get_entity(self, entity_id: str) -> Optional[KGEntityNode]:
        if KGPermission.READ not in self._permissions:
            raise SecurityViolationError("Analyzer lacks KGPermission.READ permission.")
        return self._target.get_entity(entity_id)

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        confidence: float = 1.0,
        analyzer_name: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if KGPermission.MUTATE_EDGES not in self._permissions:
            raise SecurityViolationError(
                "Analyzer lacks KGPermission.MUTATE_EDGES permission to add_edge."
            )
        self._target.add_edge(
            source_id, target_id, relation_type, confidence, analyzer_name, metadata
        )

    def get_outgoing_edges(
        self, node_id: str, relation_type: Optional[RelationType] = None
    ) -> List[KGEdge]:
        if KGPermission.READ not in self._permissions:
            raise SecurityViolationError("Analyzer lacks KGPermission.READ permission.")
        return self._target.get_outgoing_edges(node_id, relation_type)

    def get_incoming_edges(
        self, node_id: str, relation_type: Optional[RelationType] = None
    ) -> List[KGEdge]:
        if KGPermission.READ not in self._permissions:
            raise SecurityViolationError("Analyzer lacks KGPermission.READ permission.")
        return self._target.get_incoming_edges(node_id, relation_type)

    def to_json_dict(self) -> Dict[str, Any]:
        if KGPermission.READ not in self._permissions:
            raise SecurityViolationError("Analyzer lacks KGPermission.READ permission.")
        return self._target.to_json_dict()


class GuardedKnowledgeDocument(KnowledgeDocument):
    """
    Proxy wrapper around KnowledgeDocument that enforces KRMPermission checks.
    """

    def __init__(
        self, target_doc: KnowledgeDocument, permissions: Set[KRMPermission]
    ) -> None:
        object.__setattr__(self, "_target", target_doc)
        object.__setattr__(self, "_permissions", permissions)
        object.__setattr__(self, "_initializing", True)
        super().__init__(
            id=target_doc.id,
            visual_layout=target_doc.visual_layout,
            confidence_score=target_doc.confidence_score,
            is_tombstoned=target_doc.is_tombstoned,
            metadata=target_doc.metadata,
            provenance_info=target_doc.provenance_info,
            title=target_doc.title,
            source_uri=target_doc.source_uri,
            source_type=target_doc.source_type,
            root_containers=target_doc.root_containers,
        )
        object.__setattr__(self, "_initializing", False)

    def __getattribute__(self, name: str) -> Any:
        if name in ("_target", "_permissions", "_initializing"):
            return object.__getattribute__(self, name)

        if object.__getattribute__(self, "_initializing"):
            return object.__getattribute__(self, name)

        try:
            permissions = object.__getattribute__(self, "_permissions")
            target = object.__getattribute__(self, "_target")
        except AttributeError:
            return object.__getattribute__(self, name)

        if KRMPermission.READ not in permissions:
            raise SecurityViolationError(
                f"Analyzer lacks KRMPermission.READ permission to access '{name}'."
            )

        return getattr(target, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_target", "_permissions", "_initializing"):
            object.__setattr__(self, name, value)
            return

        if getattr(self, "_initializing", False):
            object.__setattr__(self, name, value)
            return

        try:
            permissions = object.__getattribute__(self, "_permissions")
            target = object.__getattribute__(self, "_target")
        except AttributeError:
            object.__setattr__(self, name, value)
            return

        if name == "is_tombstoned" and value is True:
            if KRMPermission.TOMBSTONE not in permissions:
                raise SecurityViolationError(
                    "Analyzer lacks KRMPermission.TOMBSTONE permission to tombstone node."
                )
        else:
            if KRMPermission.MUTATE_ATTRIBUTES not in permissions:
                raise SecurityViolationError(
                    f"Analyzer lacks KRMPermission.MUTATE_ATTRIBUTES permission to set '{name}'."
                )

        setattr(target, name, value)
        object.__setattr__(self, name, value)


class PipelineRunner:
    """
    Pipeline Engine responsible for validating dependency order, enforcing permissions,
    and running analyzers sequentially while updating provenance tracking.
    """

    def __init__(self, analyzers: List[BaseAnalyzer]) -> None:
        self._validate_dependencies(analyzers)
        self._analyzers = list(analyzers)

    def _validate_dependencies(self, analyzers: List[BaseAnalyzer]) -> None:
        """
        Validates that all depends_on requirements are satisfied in preceding analyzer order.
        Raises ValueError if a dependency is missing or ordered after the dependent analyzer.
        """
        registered_names: Set[str] = set()

        for analyzer in analyzers:
            name = analyzer.manifest.name
            for dep in analyzer.manifest.depends_on:
                if dep not in registered_names:
                    raise ValueError(
                        f"Pipeline configuration error: Analyzer '{name}' depends on '{dep}', "
                        f"but '{dep}' is missing or placed after '{name}' in the pipeline."
                    )
            registered_names.add(name)

    def _record_provenance_recursive(self, node: BaseKRMNode, analyzer_name: str) -> None:
        """
        Recursively visits all KRM nodes in the document tree to record the analyzer_name
        in provenance_info.applied_analyzers.
        """
        utc_now = datetime.now(timezone.utc).isoformat()

        if node.provenance_info is None:
            node.provenance_info = ProvenanceInfo(
                adapter_name="PipelineRunner",
                extraction_timestamp_utc=utc_now,
                applied_analyzers=[analyzer_name],
            )
        elif analyzer_name not in node.provenance_info.applied_analyzers:
            node.provenance_info.applied_analyzers.append(analyzer_name)

        # Recurse down container and block hierarchies
        if isinstance(node, KnowledgeDocument):
            for container in node.root_containers:
                self._record_provenance_recursive(container, analyzer_name)
        elif isinstance(node, ContainerUnit):
            for child in node.children:
                self._record_provenance_recursive(child, analyzer_name)
        elif isinstance(node, ParagraphBlock):
            for inline in node.inlines:
                self._record_provenance_recursive(inline, analyzer_name)
        elif isinstance(node, TableBlock):
            for row in node.grid:
                for cell in row:
                    self._record_provenance_recursive(cell, analyzer_name)
                    for block in cell.content:
                        self._record_provenance_recursive(block, analyzer_name)
        elif isinstance(node, ListBlock):
            for item in node.items:
                self._record_provenance_recursive(item, analyzer_name)
        elif isinstance(node, ListItemBlock):
            for block in node.content:
                self._record_provenance_recursive(block, analyzer_name)
        elif isinstance(node, CalloutBlock):
            for block in node.content:
                self._record_provenance_recursive(block, analyzer_name)
        elif isinstance(node, InlineUnit):
            for span in node.spans:
                self._record_provenance_recursive(span, analyzer_name)

    def execute(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Any] = None,
    ) -> None:
        """
        Executes all analyzers in sequence with permission guards and records provenance.
        on_progress: optional callback(step: int, total: int, analyzer_name: str)
        """
        total = len(self._analyzers)
        for step, analyzer in enumerate(self._analyzers):
            manifest = analyzer.manifest

            if on_progress:
                on_progress(step, total, manifest.name)

            # RFC 0005 §6.1 Failure Isolation: snapshot doc/rg/kg before the run so
            # a crashing analyzer is rolled back and the pipeline continues from the
            # pre-run state instead of leaving a half-mutated document.
            doc_snap = copy.deepcopy(doc)
            rg_snap = copy.deepcopy(rg)
            kg_snap = copy.deepcopy(kg)

            guarded_doc = GuardedKnowledgeDocument(doc, manifest.krm_permissions)
            guarded_rg = GuardedReadingGraph(rg, manifest.rg_permissions)
            guarded_kg = GuardedKnowledgeGraph(kg, manifest.kg_permissions)

            try:
                analyzer.run(guarded_doc, guarded_rg, guarded_kg, context)
            except SecurityViolationError:
                raise
            except Exception:
                logging.getLogger(__name__).exception(
                    "Analyzer '%s' failed; rolling back to pre-run state (RFC 0005 §6.1)",
                    manifest.name,
                )
                self._restore_state(doc, doc_snap)
                self._restore_state(rg, rg_snap)
                self._restore_state(kg, kg_snap)
                continue

            # Upon successful run, log analyzer in provenance info across KRM nodes
            if KRMPermission.READ in manifest.krm_permissions:
                self._record_provenance_recursive(doc, manifest.name)

        # RFC 0003 §5.1: verify no dangling KG edges after the pipeline completes.
        krm_ids = self._collect_krm_ids(doc)
        violations = kg.validate_integrity(krm_ids)
        if violations:
            logging.getLogger(__name__).warning(
                "KG integrity: %d dangling edge endpoint(s): %s",
                len(violations), "; ".join(violations[:10]),
            )

        if on_progress:
            on_progress(total, total, "done")

    def _collect_krm_ids(self, doc: KnowledgeDocument) -> Set[str]:
        ids: Set[str] = set()

        def walk(node: BaseKRMNode) -> None:
            ids.add(node.id)
            if isinstance(node, ContainerUnit):
                for child in node.children:
                    walk(child)
            elif isinstance(node, ParagraphBlock):
                for inline in node.inlines:
                    ids.add(inline.id)
                    for span in inline.spans:
                        ids.add(span.id)
            elif isinstance(node, TableBlock):
                for row in node.grid:
                    for cell in row:
                        ids.add(cell.id)
                        for block in cell.content:
                            walk(block)
            elif isinstance(node, ListBlock):
                for item in node.items:
                    walk(item)
            elif isinstance(node, ListItemBlock):
                for block in node.content:
                    walk(block)
            elif isinstance(node, CalloutBlock):
                for block in node.content:
                    walk(block)

        for container in doc.root_containers:
            walk(container)
        return ids

    @staticmethod
    def _restore_state(target: Any, snapshot: Any) -> None:
        """Restore a live object in place from a deep-copied snapshot (rollback)."""
        target.__dict__.clear()
        target.__dict__.update(snapshot.__dict__)
