"""bibliography: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.bibliography.signals import _BIB_TITLES, _NUMBERED_RE, _YEAR_RE
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    BibEntryBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

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
