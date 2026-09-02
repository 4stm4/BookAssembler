"""index: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import first_span_text
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
    ContainerUnit,
    IndexEntryBlock,
    KnowledgeDocument,
    ParagraphBlock,
)

from src.analyzers.index.signals import _INDEX_ENTRY_RE, _INDEX_TITLE_RE
from src.analyzers.index.rules import _parse_page_refs

class IndexDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="IndexDetectorAnalyzer",
                version="1.0.0",
                description="Detect back-of-book index entries in Index containers",
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

        if not _INDEX_TITLE_RE.match(container.title.strip()):
            return

        new_children: List[Any] = []
        for child in container.children:
            if isinstance(child, ContainerUnit):
                new_children.append(child)
                continue
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                new_children.append(child)
                continue
            if type(child) is not ParagraphBlock:
                new_children.append(child)
                continue

            text = first_span_text(child)
            m = _INDEX_ENTRY_RE.match(text) if text else None
            if not m:
                new_children.append(child)
                continue

            entry = IndexEntryBlock(
                term=m.group("term").strip(),
                page_refs=_parse_page_refs(m.group("pages")),
                visual_layout=child.visual_layout,
                extraction_confidence=child.extraction_confidence,
                classification_confidence=0.85,
                confidence_score=min(child.extraction_confidence, 0.85),
            )
            entry.id = child.id
            new_children.append(entry)

        container.children = new_children
