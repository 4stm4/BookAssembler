"""font_stats: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.font_stats.signals import CAPTION_SIZE_RATIO, FOOTNOTE_SIZE_RATIO, HEADING_SIZE_RATIO, _MATH_HINTS, _MONO_HINTS, log
from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

@dataclass
class FontFingerprint:
    family: str
    size: float
    bold: bool
    italic: bool

    @property
    def key(self) -> str:
        return f"{self.family}|{self.size:.1f}|{int(self.bold)}|{int(self.italic)}"

def _extract_font(block: ParagraphBlock) -> Optional[FontFingerprint]:
    vl = getattr(block, "visual_layout", None)
    if not vl:
        return None
    style = getattr(vl, "style", None)
    if not style:
        return None
    family = (getattr(style, "font_family", "") or "").strip()
    size = getattr(style, "font_size_pt", 0.0) or 0.0
    bold = bool(getattr(style, "is_bold", False))
    italic = bool(getattr(style, "is_italic", False))
    if not family and size == 0.0:
        return None
    return FontFingerprint(family=family.lower(), size=size, bold=bold, italic=italic)

def _classify_role(
    fp: FontFingerprint,
    body_family: str,
    body_size: float,
) -> str:
    family = fp.family

    if any(hint in family for hint in _MATH_HINTS):
        return "math"
    if any(hint in family for hint in _MONO_HINTS):
        return "code"

    if body_size > 0:
        ratio = fp.size / body_size if fp.size > 0 else 1.0
        if ratio >= HEADING_SIZE_RATIO:
            return "heading"
        if ratio <= FOOTNOTE_SIZE_RATIO:
            return "footnote"
        if ratio <= CAPTION_SIZE_RATIO:
            return "caption"

    if fp.bold and fp.size >= body_size and family == body_family:
        return "heading"

    return "body"
