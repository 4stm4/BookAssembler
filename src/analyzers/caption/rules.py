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
    """Nearest live block of `classes`, preferring one BEFORE the caption.

    `children` indices are not a reliable stand-in for vertical distance on
    the page: a table's own absorbed rows (RFC 0001 SS2.4 - tombstoned in
    place, never removed) can occupy dozens of index slots between a table
    and the caption printed right under it, while the NEXT table starts
    only a couple of slots after that same caption. Plain index distance
    then picks the next table over the one the caption actually sits under
    (found on the messy voltage-regulator fixture: "Figure 1.14" - the
    mA7812 table's own caption - linked to the mA7912 table two slots
    after it instead of the mA7812 table 24 slots before it). A caption
    describes what it follows, so a preceding candidate wins at any
    distance before a following one is even considered.
    """
    best_before_id = None
    best_before_dist = float("inf")
    best_after_id = None
    best_after_dist = float("inf")
    for i, child in enumerate(children):
        # A tombstoned block absorbed into a merged neighbor (e.g.
        # TableDetectorAnalyzer._merge_adjacent_tables folding several
        # fragment TableBlocks into one) stays in the tree in place (RFC
        # 0001 SS2.4: no physical deletion) - linking to its id points the
        # caption at dead content instead of the table actually printed
        # under it.
        if getattr(child, "is_tombstoned", False):
            continue
        if not isinstance(child, classes):
            continue
        dist = abs(i - caption_idx)
        if i <= caption_idx:
            if dist < best_before_dist:
                best_before_dist = dist
                best_before_id = child.id
        elif dist < best_after_dist:
            best_after_dist = dist
            best_after_id = child.id
    return best_before_id if best_before_id is not None else best_after_id


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
