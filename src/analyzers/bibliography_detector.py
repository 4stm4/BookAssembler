"""
BibliographyDetectorAnalyzer — find "References" / "Bibliography" /
«Литература» containers and promote their ParagraphBlock children to
BibEntryBlock (KRM_ENTITIES_MAP P1.6).

The container itself is marked with semantic_type='bibliography' so
downstream consumers (assembler, chunker, KG) can special-case it.
"""

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
    BibEntryBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)


_BIB_TITLES = (
    "bibliography", "references", "works cited", "литература",
    "библиография", "список литературы", "источники",
)

_NUMBERED_RE = re.compile(r"^\s*\[(?P<n>\d+)\]\s*(?P<rest>.*)$")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2}|21\d{2})\b")


def _block_text(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                parts.append(txt)
    return " ".join(parts).strip()


def _is_bib_container(container: ContainerUnit) -> bool:
    if container.semantic_type == "bibliography":
        return True
    title = (container.title or "").strip().lower()
    if not title:
        return False
    for hint in _BIB_TITLES:
        if hint in title:
            return True
    return False


def _fabricate_key(authors: List[str], year: Optional[int]) -> str:
    author_part = ""
    if authors:
        last = authors[0].split()[-1] if authors[0] else ""
        author_part = re.sub(r"\W+", "", last).lower()
    if not author_part:
        author_part = "ref"
    year_part = str(year) if year else "nd"
    return f"{author_part}{year_part}"


def _parse_entry(text: str) -> Tuple[str, List[str], Optional[int], str, str]:
    """Return (cite_key, authors, year, title, raw_text)."""
    raw = re.sub(r"\s+", " ", text.strip())

    m_num = _NUMBERED_RE.match(raw)
    numbered_key: Optional[str] = None
    body = raw
    if m_num:
        numbered_key = m_num.group("n")
        body = m_num.group("rest").strip()

    year: Optional[int] = None
    m_year = _YEAR_RE.search(body)
    if m_year:
        year = int(m_year.group(1))

    # Author list up to the first '.' that's followed by a capital letter or
    # digit — the classic "Knuth, D. E. The Art …" boundary.
    m_split = re.match(r"^(?P<authors>[^.]{2,120}?)\.\s+(?P<rest>[A-ZА-Я0-9].*)$", body)
    authors: List[str] = []
    title = body
    if m_split:
        author_field = m_split.group("authors").strip(" .,")
        authors = [p.strip() for p in re.split(r",\s+(?=[A-ZА-Я])|;\s+", author_field) if p.strip()]
        rest = m_split.group("rest").strip()
        # Title = up to next '.'
        m_title = re.match(r"^(?P<title>[^.]{2,300})\.", rest)
        if m_title:
            title = m_title.group("title").strip()
        else:
            title = rest

    cite_key = numbered_key or _fabricate_key(authors, year)
    return cite_key, authors, year, title, raw


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

            text = _block_text(child)
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
