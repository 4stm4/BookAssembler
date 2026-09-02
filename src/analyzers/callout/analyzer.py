"""callout: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import first_span_text
import re
from typing import Any, Dict, List, Optional, Tuple
from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    CalloutBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)

from src.analyzers.callout.rules import _classify, _replace_first_text

class CalloutDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="CalloutDetectorAnalyzer",
                version="1.0.0",
                description="Promote 'Note:'/'Warning:'/… paragraphs to CalloutBlock",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.INSERT,
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
            # Do not re-wrap already-typed subclasses (TitlePageBlock etc.)
            if type(child) is not ParagraphBlock:
                new_children.append(child)
                continue

            text = first_span_text(child)
            classified = _classify(text) if text else None
            if not classified:
                new_children.append(child)
                continue

            kind, severity, label, remainder = classified
            _replace_first_text(child, remainder.strip())
            callout = CalloutBlock(
                kind=kind,
                severity=severity,
                label=label.strip(),
                content=[child],
                visual_layout=child.visual_layout,
                extraction_confidence=child.extraction_confidence,
                classification_confidence=0.85,
                confidence_score=min(child.extraction_confidence, 0.85),
            )
            callout.id = child.id  # RFC 0001 §2.3
            new_children.append(callout)

        container.children = new_children
