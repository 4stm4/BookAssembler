"""normalization: The analyzer itself: orchestration and KRM writes."""

from typing import Any, Dict, List, Optional
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    BaseKRMNode,
    ContainerUnit,
    InlineUnit,
    KnowledgeDocument,
    ParagraphBlock,
    SpanUnit,
    TableBlock,
)

from src.analyzers.normalization.signals import _WS_RE
from src.analyzers.normalization.rules import _collect_spans

class NormalizationAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="NormalizationAnalyzer",
                version="1.0.0",
                description="Normalizes whitespace in span text",
                krm_permissions={KRMPermission.READ, KRMPermission.MUTATE_ATTRIBUTES},
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=[],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        for span in _collect_spans(doc):
            original = span.text
            if not original:
                continue
            normalized = _WS_RE.sub(" ", original).strip()
            if normalized != original:
                change_ratio = abs(len(original) - len(normalized)) / max(len(original), 1)
                span.text = normalized
                span.confidence_score = max(0.5, 1.0 - change_ratio)
