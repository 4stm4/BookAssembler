import re
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

_WS_RE = re.compile(r"\s+")


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


def _collect_spans(doc: KnowledgeDocument) -> List[SpanUnit]:
    spans: List[SpanUnit] = []

    def _walk(node: BaseKRMNode) -> None:
        if isinstance(node, SpanUnit):
            spans.append(node)
        elif isinstance(node, ContainerUnit):
            for child in node.children:
                _walk(child)
        elif isinstance(node, ParagraphBlock):
            for inline in node.inlines:
                _walk(inline)
        elif isinstance(node, InlineUnit):
            for span in node.spans:
                _walk(span)
        elif isinstance(node, TableBlock):
            for row in node.grid:
                for cell in row:
                    for content_node in cell.content:
                        _walk(content_node)

    for container in doc.root_containers:
        _walk(container)
    return spans
