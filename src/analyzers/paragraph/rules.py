"""paragraph: Pure decision logic - no KRM writes, no I/O."""

from statistics import median
from typing import Any, List, Optional

# A first line starting this far (page share) right of a paragraph's body
# is indented: a new paragraph begins there.
INDENT_TOL = 0.008
# A last line ending this far (page share) short of its paragraph's right
# edge ends the paragraph.
SHORT_LINE_TOL = 0.03
# Two lines stand on one paragraph's pitch within this share of it.
PITCH_TOL = 0.35


def line_boxes(paragraph: Any) -> List[Any]:
    """A paragraph's lines' boxes, top to bottom, where it kept them."""
    boxes = [il.visual_layout.bounding_box for il in (paragraph.inlines or [])
             if getattr(il, "visual_layout", None) is not None and il.visual_layout.bounding_box is not None]
    return sorted(boxes, key=lambda b: b.y0)


def _pitch(boxes: List[Any]) -> Optional[float]:
    steps = [b.y1 - a.y1 for a, b in zip(boxes, boxes[1:]) if b.y1 > a.y1]
    return median(steps) if steps else None


def continues(prev: Any, nxt: Any) -> bool:
    """Whether paragraph nxt is the rest of paragraph prev, cut off from it -
    OCR split the paragraph fixture's one paragraph into three blocks: in
    prev's column, its first line not indented, a line's pitch under prev's
    last line, which runs to the column's right edge."""
    a, b = line_boxes(prev), line_boxes(nxt)
    if not a or not b:
        return False
    if prev.visual_layout.page_or_screen_index != nxt.visual_layout.page_or_screen_index:
        return False
    # where the column's unindented lines start: prev's first line may be
    # indented, and prev may be that line alone
    body_left = min(box.x0 for box in a[1:] + b)
    right = max(box.x1 for box in a + b)
    last, first = a[-1], b[0]
    if first.x0 > body_left + INDENT_TOL:
        return False
    if min(box.x0 for box in a) < body_left - INDENT_TOL:
        return False
    if last.x1 < right - SHORT_LINE_TOL:
        return False
    if len(b) > 1 and max(box.x1 for box in b) < right - SHORT_LINE_TOL:
        return False
    pitch = _pitch(a) or _pitch(b) or (last.y1 - last.y0) * 1.2
    step = first.y1 - last.y1
    return abs(step - pitch) <= PITCH_TOL * pitch
