"""heading: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.access import block_text, font_size
from collections import Counter
import re
from typing import Any, Dict, List, Optional
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock, UnknownBlock

from src.analyzers.paragraph.rules import continues
from src.analyzers.heading.signals import (
    HANGING_INDENT_LINES,
    MAX_HEADING_GAP_LINES,
    MAX_PRINTED_HEADING_WORDS,
    MIN_WORD_CHAR_RATIO,
    _COMMENT_CLOSE_RE,
    _COMMENT_OPEN_RE,
    _NOTE_PREFIX_RE,
    _TRAILING_JUNK_RE,
    _WORD_RE,
)


def _word_char_ratio(text: str) -> float:
    """Share of the text's (non-space) characters that belong to a real word.

    A diagram label or code comment mangled by OCR can embed one genuine
    word inside a run of symbol noise; this measures how much of the text
    that word actually accounts for, rather than just whether one exists.
    """
    words = [
        w for w in _WORD_RE.findall(text)
        if re.search(r"[aeiouAEIOUyY]", w) and len(set(w.lower())) >= 2
    ]
    total = len(re.sub(r"\s+", "", text))
    if not total:
        return 0.0
    return sum(len(w) for w in words) / total


def _looks_like_non_heading_noise(text: str) -> bool:
    """Syntactic tells the word-ratio check cannot reach: a mangled code
    comment, an inline "NOTE:" annotation, or a diagram/pinout label
    trailing off into scan noise. See signals.py for what each pattern
    was measured against."""
    return bool(
        _COMMENT_OPEN_RE.match(text)
        or _COMMENT_CLOSE_RE.search(text)
        or _NOTE_PREFIX_RE.match(text)
        or _TRAILING_JUNK_RE.search(text)
    )

def _is_monospace(block: Any) -> bool:
    vl = getattr(block, "visual_layout", None)
    st = getattr(vl, "style", None) if vl else None
    return bool(getattr(st, "is_monospace", False)) if st else False

def _detect_heading_threshold(sizes: List[float]) -> float:
    """Body text is the most common font size; headings are ≥25% larger."""
    if not sizes:
        return 999.0
    counts = Counter(round(s, 1) for s in sizes)
    body_size = counts.most_common(1)[0][0]
    return body_size * 1.25

def _heading_level(font_size: float, threshold: float) -> int:
    ratio = font_size / threshold if threshold else 0.0
    if ratio >= 1.4:
        return 1
    if ratio >= 1.15:
        return 2
    return 3

def _reads_as_title(text: str) -> bool:
    """Whether text has a heading's shape: words, not noise."""
    return (
        3 <= len(text) < 200
        and any(c.isalpha() for c in text)
        and _word_char_ratio(text) >= MIN_WORD_CHAR_RATIO
        and not _looks_like_non_heading_noise(text)
    )


def _is_heading(block: Any, threshold: float) -> bool:
    if not isinstance(block, (ParagraphBlock, UnknownBlock)):
        return False
    if _is_monospace(block):
        return False
    return font_size(block, default=12.0) >= threshold and _reads_as_title(block_text(block))


def _printed(block: Any) -> List[Dict[str, Any]]:
    """A block's lines as printed (PrintedLinesAnalyzer), where read."""
    if not isinstance(block, (ParagraphBlock, UnknownBlock)):
        return []
    return list((block.metadata or {}).get("printed_lines") or [])


def _printed_under(blocks: List[Any], start: int) -> List[Dict[str, Any]]:
    """The printed lines of the paragraph blocks[start] starts: it and the
    blocks after it that continue it (paragraph.rules.continues) - OCR cuts
    a paragraph into pieces, and its first line can stand alone."""
    lines: List[Dict[str, Any]] = []
    k = start
    while k < len(blocks) and isinstance(blocks[k], (ParagraphBlock, UnknownBlock)):
        if k > start and not continues(blocks[k - 1], blocks[k]):
            break
        lines += _printed(blocks[k])
        k += 1
    return lines


def _is_printed_heading(block: Any, under: List[Dict[str, Any]]) -> bool:
    """A scanned page's heading set in body size: one line standing over
    the paragraph it heads (under, its printed lines, set regular), set
    apart from it by its weight - the paragraph fixtures' "INTRODUCTION",
    "REFRESH CYCLES" - or by hanging out to its left - "PUSH IX" over its
    instruction. As tall as the body, the size rule cannot tell it; its
    text layer calls nothing bold."""
    lines = _printed(block)
    if len(lines) != 1 or len(block.inlines or []) != 1 or _is_monospace(block):
        return False
    text = block_text(block)
    if not _reads_as_title(text) or len(text.split()) > MAX_PRINTED_HEADING_WORDS:
        return False
    if len(under) < 2 or under[0]["bold"] or under[0]["page"] != lines[0]["page"]:
        return False
    x0, top, x1, bottom = lines[0]["box"]
    utop = under[0]["box"][1]
    left = min(l["box"][0] for l in under)
    right = max(l["box"][2] for l in under)
    if not bottom <= utop <= bottom + MAX_HEADING_GAP_LINES * (bottom - top):
        return False
    if lines[0]["bold"]:
        return left < x1 and x0 < right
    return x1 <= right and x0 < left - HANGING_INDENT_LINES * (bottom - top)


def _collect_containers(
    containers: List[ContainerUnit], result: List[ContainerUnit]
) -> None:
    for c in containers:
        result.append(c)
        child_containers = [ch for ch in c.children if isinstance(ch, ContainerUnit)]
        if child_containers:
            _collect_containers(child_containers, result)
