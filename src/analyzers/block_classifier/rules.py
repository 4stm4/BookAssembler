"""block_classifier: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.block_classifier.signals import MAX_TOC_TEXT_LEN, MIN_TOC_RUN, _ENDS_WITH_PAGE_NUM, _LEADING_NUM_RE
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    TextLineInline,
    TocEntryBlock,
    StyledTextSpan,
    VisualLayout,
    NormalizedRect,
)

def _parse_toc_entry(text: str) -> Tuple[str, Optional[str], Optional[int]]:
    """
    Split "1.2  Registers .......... 45" into (entry_text, chapter_number, target_page).

    entry_text keeps the *displayed* line stripped of dot-leaders so the user
    sees the same wording; chapter_number and target_page are parsed extras.
    """
    stripped = re.sub(r"\.{2,}", " ", (text or "").strip())
    stripped = re.sub(r"\s+", " ", stripped)

    target_page: Optional[int] = None
    m_page = _ENDS_WITH_PAGE_NUM.search(stripped)
    if m_page:
        raw = m_page.group(1)
        try:
            target_page = int(raw) - 1  # 0-based physical page index
        except ValueError:
            target_page = None  # roman numerals — leave unparsed for now
        stripped = _ENDS_WITH_PAGE_NUM.sub("", stripped).strip()

    chapter_number: Optional[str] = None
    m_num = _LEADING_NUM_RE.match(stripped)
    if m_num:
        if m_num.group("hier"):
            chapter_number = m_num.group("hier")
        elif m_num.group("letter"):
            chapter_number = m_num.group("letter") + "."
        elif m_num.group("roman"):
            chapter_number = m_num.group("roman") + "."
        elif m_num.group("word"):
            chapter_number = f"{m_num.group('word')} {m_num.group('word_num')}"

    return stripped, chapter_number, target_page

def _get_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)

def _looks_like_toc_entry(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > MAX_TOC_TEXT_LEN or len(stripped) < 5:
        return False
    if not _ENDS_WITH_PAGE_NUM.search(stripped):
        return False
    title_part = _ENDS_WITH_PAGE_NUM.sub("", stripped).strip()
    long_words = [w for w in title_part.split() if len(w) >= 3 and any(c.isalpha() for c in w)]
    if len(long_words) < 1:
        return False
    return True

def _classify_paragraph_confidence(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.10

    length = len(stripped)
    words = stripped.split()
    word_count = len(words)
    alpha_ratio = sum(c.isalpha() for c in stripped) / length if length else 0
    has_period = "." in stripped
    has_sentence = has_period and word_count > 3

    score = 0.50

    if has_sentence and length > 80:
        score += 0.30
    elif has_sentence:
        score += 0.20
    elif length > 50:
        score += 0.10

    if word_count >= 5:
        score += 0.05
    elif word_count == 1:
        score -= 0.15

    if alpha_ratio > 0.6:
        score += 0.05
    elif alpha_ratio < 0.3:
        score -= 0.10

    if length < 5:
        score -= 0.15

    return max(0.10, min(0.95, score))
