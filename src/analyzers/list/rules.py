"""list: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.list.signals import _BULLET_CHARS, _MARKER_RE, _ROMAN_RE
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    BaseKRMNode,
    ContainerUnit,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    ParagraphBlock,
    StructuralUnit,
)

def _first_span_text(block: ParagraphBlock) -> str:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                return str(txt)
    return ""

def _classify_marker(text: str) -> Optional[Tuple[str, str, str]]:
    """Return (list_style, marker, remainder) or None if not a list item."""
    m = _MARKER_RE.match(text)
    if not m:
        return None
    if m.group("bullet") is not None:
        style = "bullet"
    elif m.group("num") is not None:
        style = "ordered"
    elif m.group("roman") is not None and _ROMAN_RE.match(m.group("roman") or ""):
        # A single "i" or "a" is ambiguous; prefer roman only when >1 char
        # so plain "a) foo" stays alpha.
        style = "roman" if len(m.group("roman")) > 1 else "alpha"
    elif m.group("alpha") is not None:
        style = "alpha"
    else:
        return None
    marker = text[m.start(): m.end()].strip()
    remainder = text[m.end():]
    return style, marker, remainder

def _strip_marker(block: ParagraphBlock, remainder: str) -> None:
    """Replace the first span's text with `remainder`, preserving spans."""
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            if getattr(span, "text", ""):
                span.text = remainder
                return
