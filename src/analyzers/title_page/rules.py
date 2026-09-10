"""title_page: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.title_page.signals import MAX_SCAN_PAGES, MAX_TITLE_BLOCK_LEN, MIN_SCORE, TITLE_MAX_PAGES, _NodeLoc, _RE_COPYRIGHT, _RE_EDITION, _RE_ISBN, _RE_PUBLISHER, _RE_STRONG, _RE_YEAR, log
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from src.krm.models import (
    BlankPageBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    TitlePageBlock,
    TextLineInline,
    StyledTextSpan,
)

def _get_text(block: Any) -> str:
    if isinstance(block, ParagraphBlock):
        parts = []
        for inline in (block.inlines or []):
            for span in getattr(inline, "spans", []):
                if hasattr(span, "text"):
                    parts.append(span.text)
        return " ".join(parts).strip()
    if isinstance(block, ContainerUnit):
        return (block.title or "").strip()
    return ""

def _is_mostly_upper(text: str) -> bool:
    alpha = [c for c in text if c.isalpha()]
    if len(alpha) < 3:
        return False
    return sum(1 for c in alpha if c.isupper()) / len(alpha) > 0.7

def _score_page_blocks(texts: List[str]) -> int:
    score = 0
    for t in texts:
        if _is_mostly_upper(t) and len(t) > 5:
            score += 2
        if _RE_COPYRIGHT.search(t):
            score += 3
        if _RE_PUBLISHER.search(t):
            score += 2
        if _RE_ISBN.search(t):
            score += 3
        if _RE_EDITION.search(t):
            score += 2
        if _RE_YEAR.search(t) and len(t) < 60:
            score += 1
    if len(texts) >= 3 and all(len(t) < 80 for t in texts):
        score += 1
    return score

def _extract_metadata(texts: List[str]) -> Dict[str, Any]:
    title_parts: List[str] = []
    authors: List[str] = []
    publisher = ""
    edition = ""
    page_role = "title"

    for t in texts:
        if _RE_COPYRIGHT.search(t) or _RE_ISBN.search(t):
            page_role = "copyright"
        if _RE_PUBLISHER.search(t):
            publisher = t.strip()
        m = _RE_EDITION.search(t)
        if m:
            edition = m.group(0)
        if _is_mostly_upper(t) and len(t) > 5 and not _RE_COPYRIGHT.search(t):
            title_parts.append(t.strip())

    for t in texts:
        words = t.strip().split()
        if 2 <= len(words) <= 6 and all(w[0].isupper() for w in words if w[0].isalpha()):
            if not _RE_PUBLISHER.search(t) and not _RE_COPYRIGHT.search(t) and not _RE_ISBN.search(t):
                if not any(kw in t.lower() for kw in ("edition", "copyright", "press", "inc", "limited", "ltd")):
                    if not _is_mostly_upper(t) or len(words) <= 4:
                        authors.append(t.strip())

    return {
        "book_title": " ".join(title_parts),
        "authors": authors[:5],
        "publisher": publisher,
        "edition": edition,
        "page_role": page_role,
    }

