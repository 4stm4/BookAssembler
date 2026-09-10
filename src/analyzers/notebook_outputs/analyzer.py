"""notebook_outputs: links a cell output back to the code that produced it."""

from typing import Any, Dict, Optional

from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph
from src.krm.models import KnowledgeDocument
from src.krm.traversal import walk


class NotebookOutputAnalyzer(BaseAnalyzer):
    """Turns the notebook adapter's cell tagging into CONCRETIZES edges (RFC 0008 §3.4).

    The adapter records which code cell produced each output but cannot write to
    the graph — writing it here keeps graph mutation inside the permissions
    matrix (RFC 0005 §2). A no-op for documents from any other source.
    """

    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="NotebookOutputAnalyzer",
                version="1.0.0",
                description="Link notebook cell outputs to their code cell (CONCRETIZES)",
                krm_permissions={KRMPermission.READ},
                rg_permissions=set(),
                kg_permissions={KGPermission.MUTATE_EDGES},
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
        known_ids = {getattr(node, "id", None) for node in walk(doc)}

        for node in walk(doc):
            if getattr(node, "is_tombstoned", False):
                continue
            metadata = getattr(node, "metadata", None) or {}
            cell_id = metadata.get("produced_by_cell_id")
            if not cell_id or cell_id not in known_ids:
                continue

            kg.add_edge(
                node.id,
                str(cell_id),
                RelationType.CONCRETIZES,
                confidence=1.0,
                analyzer_name=self.manifest.name,
            )
