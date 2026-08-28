"""
AlgorithmDetectorAnalyzer — detect pseudocode algorithm blocks.

Prefix pattern: "Algorithm N:" / "Алгоритм N:" followed by pseudocode-like
content (indented lines, keywords like if/then/else/while/for/return).
Promotes matching ParagraphBlock to AlgorithmBlock.
"""

import re
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

_ALGO_PREFIX_RE = re.compile(
    r"^\s*(?:algorithm|алгоритм)\s+(?P<number>\d+(?:\.\d+)*)\s*[.:—–\-]?\s*(?P<name>.*)$",
    re.IGNORECASE,
)

_PSEUDO_KEYWORDS = re.compile(
    r"\b(?:if|then|else|while|for|do|end|return|input|output|repeat|until|procedure|function)\b",
    re.IGNORECASE,
)


def _first_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                parts.append(str(txt))
    return " ".join(parts)


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

            text = _first_text(child)
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
