"""formula: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.formula.signals import _FORMULA_NUMBER_RE, _MATH_CHARS, _MATH_FONT_HINTS
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    ContainerUnit,
    FormulaBlock,
    KnowledgeDocument,
    ParagraphBlock,
)

def _font_family(block: ParagraphBlock) -> str:
    vl = getattr(block, "visual_layout", None)
    st = getattr(vl, "style", None) if vl else None
    return (getattr(st, "font_family", "") or "").lower() if st else ""

def _math_font(block: ParagraphBlock) -> bool:
    font = _font_family(block)
    return any(hint in font for hint in _MATH_FONT_HINTS)

def _symbol_density(text: str) -> float:
    if not text:
        return 0.0
    hits = sum(1 for ch in text if ch in _MATH_CHARS)
    return hits / len(text)

def _looks_like_formula(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False
    density = _symbol_density(stripped)
    if density >= 0.15:
        return True
    # Equations without unicode symbols: 'x = a + b^2', 'f(x) = ...'
    if len(stripped) <= 60 and "=" in stripped and len(stripped.split()) <= 8:
        alpha = sum(1 for c in stripped if c.isalpha())
        digits_ops = sum(1 for c in stripped if c.isdigit() or c in "+-*/^=()[]{}")
        if alpha and digits_ops and digits_ops / max(1, alpha) >= 0.5:
            return True
    return False

def _extract_formula_number(text: str) -> Tuple[str, Optional[str]]:
    m = _FORMULA_NUMBER_RE.search(text.rstrip())
    if not m:
        return text, None
    return text[: m.start()].rstrip(), m.group(1)
