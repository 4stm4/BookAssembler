"""diagram: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.access import font_size
from src.analyzers.diagram.signals import LEFT_PAD, MAX_LABEL_WIDTH, MAX_LABEL_WORDS, MIN_LABELS, PAD, PROSE_LINE_CHARS, RIGHT_PAD, _RE_FIGURE_CAPTION, _RE_SUBLABEL, log
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


def _runs_on(block: Any, text: str) -> bool:
    """Whether a block is body text: more words than a label's, in lines
    of PROSE_LINE_CHARS on average - not a figure's labels run together, or
    its wires read as letters."""
    lines = max(1, len(getattr(block, "inlines", None) or []))
    return len(text.split()) > MAX_LABEL_WORDS and len(text) / lines >= PROSE_LINE_CHARS


def _size_of(block: Any) -> float:
    """The size a block is printed at: on a scanned page the size half its
    printed lines (PrintedLinesAnalyzer) are set at or under - a misread
    line of a figure's note read 11.2pt to its other's 4.3 - else its
    text's; 0 unknown."""
    sizes = sorted(l.get("size") or 0.0 for l in (getattr(block, "metadata", None) or {}).get("printed_lines") or [])
    if sizes:
        return sizes[(len(sizes) - 1) // 2]
    return font_size(block, default=0.0) or 0.0
