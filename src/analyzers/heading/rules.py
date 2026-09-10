"""heading: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.access import block_text, font_size
from collections import Counter
from typing import Any, Dict, List, Optional
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock

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

def _is_heading(block: Any, threshold: float) -> bool:
    if not isinstance(block, ParagraphBlock):
        return False
    if _is_monospace(block):
        return False
    text = block_text(block)
    return (
        font_size(block, default=12.0) >= threshold
        and 3 <= len(text) < 200
        and any(c.isalpha() for c in text)
    )

def _collect_containers(
    containers: List[ContainerUnit], result: List[ContainerUnit]
) -> None:
    for c in containers:
        result.append(c)
        child_containers = [ch for ch in c.children if isinstance(ch, ContainerUnit)]
        if child_containers:
            _collect_containers(child_containers, result)
