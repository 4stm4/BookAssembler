"""
IndexDetectorAnalyzer — detect back-of-book index entries.

Finds containers titled Index/Указатель/Предметный указатель, then promotes
children matching "Term, p1, p2-p3" to IndexEntryBlock.
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
    ContainerUnit,
    IndexEntryBlock,
    KnowledgeDocument,
    ParagraphBlock,
)

_INDEX_TITLE_RE = re.compile(
    r"^(?:index|указатель|предметный\s+указатель|subject\s+index)$",
    re.IGNORECASE,
)

_INDEX_ENTRY_RE = re.compile(
    r"^(?P<term>.+?)\s*,\s*(?P<pages>(?:\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*)?)+)\s*$"
)


def _first_text(block: ParagraphBlock) -> str:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                return str(txt)
    return ""


def _parse_page_refs(raw: str) -> List[str]:
    return [r.strip() for r in raw.split(",") if r.strip()]


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

            text = _first_text(child)
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
