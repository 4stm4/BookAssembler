"""normalization: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.normalization.signals import _WS_RE
import re
from typing import Any, Dict, List, Optional
from src.krm.models import (
    BaseKRMNode,
    ContainerUnit,
    InlineUnit,
    KnowledgeDocument,
    ParagraphBlock,
    SpanUnit,
    TableBlock,
)

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
