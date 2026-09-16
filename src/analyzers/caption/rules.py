"""caption: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.caption.signals import _CAPTION_RE, _EXAMPLE_HEADING_RE, _TARGET_TYPE_MAP
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    FigureBlock,
    FormulaBlock,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TableBlock,
    TextLineInline,
)

_ATOMIC_CLASSES = (FigureBlock, TableBlock, CodeBlock, FormulaBlock)

def _get_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)

def _nearest_of(children: list, caption_idx: int, classes: tuple) -> Optional[str]:
    best_id = None
    best_dist = float("inf")
    for i, child in enumerate(children):
        if isinstance(child, classes):
            dist = abs(i - caption_idx)
            if dist < best_dist:
                best_dist = dist
                best_id = child.id
    return best_id


def _find_nearest_target(
    children: list,
    caption_idx: int,
    target_type: str,
) -> Optional[str]:
    """Find the nearest block of matching type before or after caption_idx.

    Falls back to the nearest atomic block of ANY kind (figure/table/code/
    formula) when none of the declared type exists nearby: a source labels
    its own captions by convention, not by KRM type, and "Fig." sometimes
    heads what TableDetectorAnalyzer correctly recognizes as a TableBlock
    (Fig. 1.2 "Decimal-Binary Table" is one - a real book, not a made-up
    case). Losing the caption link entirely over a type-word mismatch would
    be worse than linking it to whatever atomic block is actually nearest.
    """
    target_classes = {
        "figure": FigureBlock,
        "table": TableBlock,
    }
    cls = target_classes.get(target_type)
    exact = _nearest_of(children, caption_idx, (cls,)) if cls is not None else None
    if exact is not None:
        return exact
    return _nearest_of(children, caption_idx, _ATOMIC_CLASSES)
