"""diagram: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.access import font_size
from src.analyzers.diagram.signals import LEFT_PAD, MAX_LABEL_WIDTH, MAX_LABEL_WORDS, MIN_LABELS, PAD, PROSE_LINE_CHARS, RIGHT_PAD, SMALLER, _RE_FIGURE_CAPTION, _RE_SUBLABEL, log
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
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


Box = Tuple[float, float, float, float]


def figure_area(labels: List[Box], prose: List[Box], band: Tuple[float, float]) -> Box:
    """Where a figure stands on its page (page-normalised): the band between
    its caption and the body text across from it (band, top and bottom),
    across the page but for the columns of body text running down beside
    it, its labels between them."""
    lo, hi = band
    middle = (min(b[0] for b in labels) + max(b[2] for b in labels)) / 2
    left, right = 0.0, 1.0
    for b in prose:
        if b[1] < hi and b[3] > lo:
            if (b[0] + b[2]) / 2 < middle:
                left = max(left, b[2])
            else:
                right = min(right, b[0])
    return (left, lo, right, hi)


def is_caption(text: str) -> bool:
    """Whether a block's text is a figure's caption ("Figure 2-11
    Data-related addressing modes") - short, no reference to one in the
    text ("Figure 2-5 shows how a program's code ...")."""
    return bool(text and _RE_FIGURE_CAPTION.match(text) and len(text.split()) <= 10)


def is_small(size: float, body: float, tall: float, body_tall: float, text: str) -> bool:
    """Whether a line by a drawing is set smaller than the page's body
    (SMALLER): by its print's size against the body's, or by how tall its
    letters' ink stands (tall, ink.letters) against the body's - where it
    has a capital, a figure, an ascender or a descender to stand so tall
    ("ns" has none).
    Either may read it too large - a label's line box its drawing's strokes
    cross, capitals against the body's ascenders - neither too small. A
    line with no letter's ink of its own is strokes OCR read as letters."""
    if not tall:
        return True
    if size and body and size < SMALLER * body:
        return True
    has_tall = any(ch.isupper() or ch.isdigit() or ch in "bdfhklgjpqy" for ch in text)
    return bool(body_tall) and has_tall and tall < SMALLER * body_tall


def near(a: Box, b: Box, reach: Tuple[float, float]) -> bool:
    """Whether two boxes stand within reach (across, down) of one another."""
    return (a[0] - reach[0] <= b[2] and b[0] <= a[2] + reach[0]
            and a[1] - reach[1] <= b[3] and b[1] <= a[3] + reach[1])


def holds(area: Box, box: Box) -> bool:
    """Whether a box stands in an area: its middle does."""
    return area[0] <= (box[0] + box[2]) / 2 <= area[2] and area[1] <= (box[1] + box[3]) / 2 <= area[3]


def over(boxes: Sequence[Box]) -> Box:
    """The box about boxes."""
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def drawings(strokes: List[Box], text: Sequence[Box], gap: Tuple[float, float]) -> List[List[int]]:
    """Which of a page's drawn strokes (their boxes) make one drawing, each
    drawing its strokes' numbers: strokes within gap (across, down) of one
    another, and - a drawing's parts stand apart: the two registers of
    Zaks' "Shift and Rotate", a timing diagram's waveforms - parts over one
    another or side by side with none of the page's text (text, its boxes)
    between them."""
    parts = _linked(strokes, lambda a, b: near(a, b, gap))
    merged = True
    while merged:
        merged = False
        boxes = [over([strokes[k] for k in part]) for part in parts]
        for i in range(len(parts)):
            j = next((j for j in range(i + 1, len(parts)) if _nothing_between(boxes[i], boxes[j], text)), None)
            if j is not None:
                parts[i] += parts.pop(j)
                merged = True
                break
    return parts


def _linked(boxes: List[Box], together: Any) -> List[List[int]]:
    """Boxes' numbers in groups: each with those it stands together with,
    and those they do."""
    group = list(range(len(boxes)))

    def root(k: int) -> int:
        while group[k] != k:
            group[k] = group[group[k]]
            k = group[k]
        return k

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if root(i) != root(j) and together(boxes[i], boxes[j]):
                group[root(j)] = root(i)
    out: Dict[int, List[int]] = {}
    for k in range(len(boxes)):
        out.setdefault(root(k), []).append(k)
    return list(out.values())


def between(a: Box, b: Box) -> Optional[Box]:
    """The stretch of the page between two boxes standing over one another
    or side by side; None where they stand neither way, or one on the
    other."""
    across = a[0] < b[2] and b[0] < a[2]
    down = a[1] < b[3] and b[1] < a[3]
    if across == down:
        return None
    if across:
        return (min(a[0], b[0]), min(a[3], b[3]), max(a[2], b[2]), max(a[1], b[1]))
    return (min(a[2], b[2]), min(a[1], b[1]), max(a[0], b[0]), max(a[3], b[3]))


def meets(a: Box, b: Box) -> bool:
    """Whether two boxes share any of the page."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _nothing_between(a: Box, b: Box, text: Sequence[Box]) -> bool:
    """Whether two boxes stand one on the other, or over one another or
    side by side with none of text between them."""
    if meets(a, b):
        return True
    gap = between(a, b)
    return gap is not None and not any(meets(t, gap) for t in text)
