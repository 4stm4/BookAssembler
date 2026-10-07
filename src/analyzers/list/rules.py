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


def _line_text(inline: Any) -> str:
    return "".join(getattr(s, "text", "") for s in getattr(inline, "spans", []) or []).strip()


def _items_in_block(block: Any) -> Optional[List[List[Any]]]:
    """A block's lines as list items, where OCR set a list in one block: its
    first line and at least one more start with a marker, numbered on from
    one another where numbered; a line with none goes on the item above.
    None where the block is no list."""
    lines = list(block.inlines or [])
    if len(lines) < 2:
        return None
    marked = [_classify_marker(_line_text(il)) for il in lines]
    if marked[0] is None or sum(m is not None for m in marked) < 2:
        return None
    numbers = [int(m[1].rstrip(".)—– ")) for m in marked if m is not None and m[0] == "ordered"
               and m[1].rstrip(".)—– ").isdigit()]
    if numbers and numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return None
    items: List[List[Any]] = []
    for il, m in zip(lines, marked):
        if m is not None or not items:
            items.append([il])
        else:
            items[-1].append(il)
    return items
