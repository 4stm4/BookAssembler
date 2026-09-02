"""diagram: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.diagram.signals import LEFT_PAD, MAX_LABEL_WIDTH, MAX_LABEL_WORDS, MIN_LABELS, PAD, RIGHT_PAD, _RE_FIGURE_CAPTION, _RE_SUBLABEL, log
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    ContainerUnit,
    DiagramBlock,
    KnowledgeDocument,
    ParagraphBlock,
    VisualLayout,
    NormalizedRect,
)

def _text_of(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts).strip()

def _bbox_of(block: Any) -> Optional[Tuple[float, float, float, float]]:
    vl = getattr(block, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    if bb is None:
        return None
    return (bb.x0, bb.y0, bb.x1, bb.y1)

