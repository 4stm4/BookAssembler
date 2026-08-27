"""
CitationLinkerAnalyzer — link inline citations [N] to BibEntryBlock entities
and create AUTHORED_BY edges from Person entities to bibliography entries.

Phase 1: scan paragraphs for [N] citation markers, find matching BibEntryBlock
         by cite_key, create CITES edge paragraph→bib_entity.
Phase 2: scan BibEntryBlock.authors, find matching PERSON entities in KG,
         create AUTHORED_BY edge person_entity→bib_entity.
"""

import re
from typing import Any, Dict, List, Optional

from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import (
    EntityType,
    KGEntityNode,
    KnowledgeGraph,
    RelationType,
)
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    BibEntryBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

_CITE_RE = re.compile(r"\[(\d+)\]")


def _first_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                parts.append(str(txt))
    return " ".join(parts)


class CitationLinkerAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="CitationLinkerAnalyzer",
                version="1.0.0",
                description="Link [N] citations to BibEntryBlock and create AUTHORED_BY edges",
                krm_permissions={KRMPermission.READ},
                rg_permissions=set(),
                kg_permissions={
                    KGPermission.READ,
                    KGPermission.MUTATE_ENTITIES,
                    KGPermission.MUTATE_EDGES,
                },
                depends_on=[
                    "NormalizationAnalyzer",
                    "BibliographyDetectorAnalyzer",
                    "ProperNounExtractorAnalyzer",
                ],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        bib_map: Dict[str, str] = {}  # cite_key → bib_entity_id
        bib_blocks: List[BibEntryBlock] = []

        for root in doc.root_containers:
            self._collect_bibs(root, kg, bib_map, bib_blocks)

        for root in doc.root_containers:
            self._link_citations(root, kg, bib_map)

        self._link_authors(bib_blocks, kg, bib_map)

    def _collect_bibs(
        self,
        container: ContainerUnit,
        kg: KnowledgeGraph,
        bib_map: Dict[str, str],
        bib_blocks: List[BibEntryBlock],
    ) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._collect_bibs(child, kg, bib_map, bib_blocks)
            elif isinstance(child, BibEntryBlock) and not child.is_tombstoned:
                entity = KGEntityNode(
                    name=child.title or child.raw_text[:60],
                    entity_type=EntityType.BIBLIOGRAPHY_CITE,
                    canonical_name=child.cite_key,
                    metadata={"year": child.year} if child.year else {},
                )
                kg.add_entity(entity)
                bib_map[child.cite_key] = entity.id
                bib_blocks.append(child)

    def _link_citations(
        self,
        container: ContainerUnit,
        kg: KnowledgeGraph,
        bib_map: Dict[str, str],
    ) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._link_citations(child, kg, bib_map)
                continue
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                continue
            text = _first_text(child)
            for m in _CITE_RE.finditer(text):
                cite_key = m.group(1)
                if cite_key in bib_map:
                    kg.add_edge(
                        source_id=child.id,
                        target_id=bib_map[cite_key],
                        relation_type=RelationType.CITES,
                        confidence=0.95,
                        analyzer_name="CitationLinkerAnalyzer",
                    )

    def _link_authors(
        self,
        bib_blocks: List[BibEntryBlock],
        kg: KnowledgeGraph,
        bib_map: Dict[str, str],
    ) -> None:
        person_entities = {
            e.canonical_name: e.id
            for e in kg._entities.values()
            if e.entity_type == EntityType.PERSON and e.canonical_name
        }
        if not person_entities:
            return

        for bib in bib_blocks:
            bib_eid = bib_map.get(bib.cite_key)
            if not bib_eid:
                continue
            for author in bib.authors:
                canonical = author.strip().lower()
                if canonical in person_entities:
                    kg.add_edge(
                        source_id=person_entities[canonical],
                        target_id=bib_eid,
                        relation_type=RelationType.AUTHORED_BY,
                        confidence=0.85,
                        analyzer_name="CitationLinkerAnalyzer",
                    )
