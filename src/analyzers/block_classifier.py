"""
BlockClassifierAnalyzer — adjusts classification_confidence for structural blocks.

Runs after other analyzers. For ParagraphBlocks that survived all detectors,
evaluates how well the block matches paragraph characteristics and adjusts
classification_confidence accordingly.

Paragraph features (high confidence):
- Multiple sentences (period + capital letter)
- Length > 50 characters
- Mostly alphabetic text with spaces

Non-paragraph features (low confidence):
- Very short text (< 10 chars)
- No sentence structure
- Mostly numeric/symbolic
- Single word
"""

from typing import Any, Dict, Optional

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)


def _get_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)


def _classify_paragraph_confidence(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.10

    length = len(stripped)
    words = stripped.split()
    word_count = len(words)
    alpha_ratio = sum(c.isalpha() for c in stripped) / length if length else 0
    has_period = "." in stripped
    has_sentence = has_period and word_count > 3

    score = 0.50

    if has_sentence and length > 80:
        score += 0.30
    elif has_sentence:
        score += 0.20
    elif length > 50:
        score += 0.10

    if word_count >= 5:
        score += 0.05
    elif word_count == 1:
        score -= 0.15

    if alpha_ratio > 0.6:
        score += 0.05
    elif alpha_ratio < 0.3:
        score -= 0.10

    if length < 5:
        score -= 0.15

    return max(0.10, min(0.95, score))


class BlockClassifierAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="BlockClassifierAnalyzer",
                version="1.0.0",
                description="Adjusts classification confidence for structural blocks",
                krm_permissions={KRMPermission.READ, KRMPermission.TRANSFORM_NODE},
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
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process_container(child)
            elif isinstance(child, ParagraphBlock):
                text = _get_text(child)
                cls_conf = _classify_paragraph_confidence(text)
                child.classification_confidence = cls_conf
                child.update_confidence()
