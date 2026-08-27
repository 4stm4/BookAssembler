"""
ProperNounExtractorAnalyzer — extract named entities (Person, Organization,
Product, Date, Version) from paragraph text using regex heuristics.

Creates KGEntityNode entries and MENTIONS_ENTITY edges from block→entity.
Deduplicates by canonical_name within the same document run.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

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
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

# Person: "A. B. Surname", "A.B. Surname", "Firstname Surname" (capitalized)
_PERSON_RE = re.compile(
    r"\b(?:"
    r"(?:[A-ZА-ЯЁ]\.[\s]?){1,3}[A-ZА-ЯЁ][a-zа-яё]{2,}"  # A. B. Surname
    r"|[A-ZА-ЯЁ][a-zа-яё]{2,}\s+[A-ZА-ЯЁ][a-zа-яё]{2,}"  # Firstname Surname
    r")\b"
)

# Organization: uppercase abbreviations (2-6 letters) or words ending with Inc/Corp/Ltd/ООО/ОАО
_ORG_RE = re.compile(
    r"\b(?:"
    r"[A-ZА-ЯЁ]{2,6}"  # DEC, IBM, IEEE
    r"|[A-ZА-ЯЁ][a-zа-яё]+(?:\s+(?:Inc|Corp|Ltd|LLC|Co|GmbH|ООО|ОАО|ЗАО))\b"
    r")"
)

# Product: alphanumeric model names with dash/numbers
_PRODUCT_RE = re.compile(
    r"\b(?:"
    r"PDP-\d{1,2}(?:/\d{1,2})?"  # PDP-11, PDP-11/70
    r"|MC\d{4,5}"  # MC68000
    r"|VAX-\d+"  # VAX-11
    r"|[A-Z]{2,4}-\d{3,6}[A-Z]?"  # ARM-926, Z80
    r"|(?:Intel|AMD|Motorola|ARM)\s+\w+"
    r")\b"
)

# Date: YYYY, DD.MM.YYYY, Month YYYY
_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[./]\d{1,2}[./]\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)

# Version: vN.N.N, version N.N
_VERSION_RE = re.compile(
    r"\b(?:v|version\s+|версия\s+)\d+(?:\.\d+){0,3}\b",
    re.IGNORECASE,
)

_PATTERNS: List[Tuple[re.Pattern, EntityType]] = [
    (_PRODUCT_RE, EntityType.PRODUCT),
    (_VERSION_RE, EntityType.VERSION),
    (_DATE_RE, EntityType.DATE),
    (_PERSON_RE, EntityType.PERSON),
]


def _first_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                parts.append(str(txt))
    return " ".join(parts)


class ProperNounExtractorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="ProperNounExtractorAnalyzer",
                version="1.0.0",
                description="Extract Person/Organization/Product/Date/Version entities via regex",
                krm_permissions={KRMPermission.READ},
                rg_permissions=set(),
                kg_permissions={
                    KGPermission.READ,
                    KGPermission.MUTATE_ENTITIES,
                    KGPermission.MUTATE_EDGES,
                },
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
        seen: Dict[str, str] = {}  # canonical_name → entity_id
        for root in doc.root_containers:
            self._process(root, kg, seen)

    def _process(
        self,
        container: ContainerUnit,
        kg: KnowledgeGraph,
        seen: Dict[str, str],
    ) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process(child, kg, seen)
                continue
            if not isinstance(child, ParagraphBlock) or child.is_tombstoned:
                continue

            text = _first_text(child)
            if not text:
                continue

            for pattern, etype in _PATTERNS:
                for m in pattern.finditer(text):
                    name = m.group(0).strip()
                    canonical = name.lower()
                    if canonical in seen:
                        eid = seen[canonical]
                    else:
                        entity = KGEntityNode(
                            name=name,
                            entity_type=etype,
                            canonical_name=canonical,
                        )
                        kg.add_entity(entity)
                        seen[canonical] = entity.id
                        eid = entity.id

                    kg.add_edge(
                        source_id=child.id,
                        target_id=eid,
                        relation_type=RelationType.MENTIONS_ENTITY,
                        confidence=0.8,
                        analyzer_name="ProperNounExtractorAnalyzer",
                    )
