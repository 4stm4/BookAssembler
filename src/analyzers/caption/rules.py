"""caption: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.caption.signals import _CAPTION_RE, _EXAMPLE_HEADING_RE, _TARGET_TYPE_MAP
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    CaptionBlock,
    ContainerUnit,
    FigureBlock,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TableBlock,
    TextLineInline,
)

def _get_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)

def _find_nearest_target(
    children: list,
    caption_idx: int,
    target_type: str,
) -> Optional[str]:
    """Find the nearest block of matching type before or after caption_idx."""
    best_id = None
    best_dist = float("inf")

    target_classes = {
        "figure": FigureBlock,
        "table": TableBlock,
    }
    cls = target_classes.get(target_type)
    if cls is None:
        return None

    for i, child in enumerate(children):
        if isinstance(child, cls):
            dist = abs(i - caption_idx)
            if dist < best_dist:
                best_dist = dist
                best_id = child.id
    return best_id
