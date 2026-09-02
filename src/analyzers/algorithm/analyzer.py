"""algorithm: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import block_text
from typing import Any, Dict, List, Optional
from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    AlgorithmBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

from src.analyzers.algorithm.signals import _ALGO_PREFIX_RE

class AlgorithmDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="AlgorithmDetectorAnalyzer",
                version="1.0.0",
                description="Detect pseudocode algorithm blocks",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.MUTATE_ATTRIBUTES,
                },
                rg_permissions=set(),
                kg_permissions={KGPermission.READ},
                depends_on=["NormalizationAnalyzer", "HeadingAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        for root in doc.root_containers:
            self._process(root)

    def _process(self, container: ContainerUnit) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child)

        new_children: List[Any] = []
        for child in container.children:
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                new_children.append(child)
                continue
            if type(child) is not ParagraphBlock:
                new_children.append(child)
                continue

            text = block_text(child)
            m = _ALGO_PREFIX_RE.match(text) if text else None
            if not m:
                new_children.append(child)
                continue

            algo = AlgorithmBlock(
                algorithm_name=m.group("name").strip(),
                algorithm_number=m.group("number"),
                pseudocode=text,
                visual_layout=child.visual_layout,
                extraction_confidence=child.extraction_confidence,
                classification_confidence=0.85,
                confidence_score=min(child.extraction_confidence, 0.85),
            )
            algo.id = child.id
            new_children.append(algo)

        container.children = new_children
