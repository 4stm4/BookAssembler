"""block_classifier: The analyzer itself: orchestration and KRM writes.

Only paragraph classification confidence lives here now. Table-of-contents
detection moved to src/analyzers/toc — it was the bulk of this file and had
nothing to do with confidence scoring.
"""

from typing import Any, Dict, List, Optional

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

from src.analyzers.block_classifier.rules import (
    _classify_paragraph_confidence,
    _get_text,
)


class BlockClassifierAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="BlockClassifierAnalyzer",
                version="2.0.0",
                description="Adjusts paragraph classification confidence",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                },
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["CaptionAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        for container in doc.root_containers:
            self._process_container(container)

    def _process_container(self, container: ContainerUnit) -> None:
        for child in list(container.children):
            if isinstance(child, ContainerUnit):
                self._process_container(child)
                continue
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                continue
            text = _get_text(child)
            child.classification_confidence = _classify_paragraph_confidence(text)
            child.update_confidence()
