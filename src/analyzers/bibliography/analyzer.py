"""bibliography: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import block_text
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
    BibEntryBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

from src.analyzers.bibliography.rules import _is_bib_container, _parse_entry

class BibliographyDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="BibliographyDetectorAnalyzer",
                version="1.0.0",
                description="Promote paragraphs inside 'References' containers to BibEntryBlock",
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
            self._walk(root)

    def _walk(self, container: ContainerUnit) -> None:
        if _is_bib_container(container):
            container.semantic_type = "bibliography"
            self._promote_children(container)
            return  # don't recurse — bib entries live at this level
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._walk(child)

    def _promote_children(self, container: ContainerUnit) -> None:
        new_children: List[Any] = []
        for child in container.children:
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                new_children.append(child)
                continue
            if type(child) is not ParagraphBlock:
                new_children.append(child)
                continue

            text = block_text(child)
            if not text or len(text) < 10:
                new_children.append(child)
                continue

            cite_key, authors, year, title, raw = _parse_entry(text)
            entry = BibEntryBlock(
                cite_key=cite_key,
                authors=authors,
                year=year,
                title=title,
                raw_text=raw,
                visual_layout=child.visual_layout,
                extraction_confidence=child.extraction_confidence,
                classification_confidence=0.80,
                confidence_score=min(child.extraction_confidence, 0.80),
            )
            entry.id = child.id  # RFC 0001 §2.3
            new_children.append(entry)

        container.children = new_children
