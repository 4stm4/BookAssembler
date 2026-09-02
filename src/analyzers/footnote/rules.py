"""footnote: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.footnote.signals import _MARKER_RE, _SUPERSCRIPT_DIGITS, _SUPER_MAP
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    ContainerUnit,
    FootnoteBlock,
    KnowledgeDocument,
    ParagraphBlock,
)

def _full_text(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                parts.append(txt)
    return "".join(parts)

def _bbox_bottom_y(block: ParagraphBlock) -> Optional[float]:
    vl = getattr(block, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    return bb.y0 if bb else None

def _parse_marker(text: str) -> Optional[Tuple[str, Optional[int], str]]:
    m = _MARKER_RE.match(text)
    if not m:
        return None
    if m.group("super"):
        marker = m.group("super")
        number = sum(_SUPER_MAP[c] * (10 ** i)
                     for i, c in enumerate(reversed(marker)))
    elif m.group("digit"):
        marker = text[m.start(): m.end()].strip()
        try:
            number = int(m.group("digit"))
        except ValueError:
            number = None
    else:
        marker = m.group("sym")
        number = None
    return marker, number, text[m.end():]
