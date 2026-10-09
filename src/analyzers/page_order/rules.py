"""page_order: pure decision logic - no KRM writes, no I/O."""

from typing import List, Optional, Sequence, Tuple

from src.analyzers.page_order.signals import COLUMN_COVER

Box = Tuple[float, float, float, float]


def reading_order(boxes: Sequence[Box], gutter: float) -> List[int]:
    """The order a page's boxes (x0, y0, x1, y1, page-normalised) are read
    in, as indices into them. Cut into columns where gaps of gutter or more
    (in the boxes' x units) run down through all of them - each column read
    after the one left of it; else into two bands at the widest gap
    running across them all - the upper read first; each part ordered so
    in its turn. What neither cuts is read row by row."""

    def ordered(items: List[int]) -> List[int]:
        if len(items) < 2:
            return items
        parts = _columns(boxes, items, gutter) or _bands(boxes, items)
        if not parts:
            return _rows(boxes, items)
        return [k for part in parts for k in ordered(part)]

    return ordered(list(range(len(boxes))))


def _covered(spans: List[Tuple[float, float]]) -> float:
    """How much of an axis the spans cover together."""
    total, end = 0.0, None
    for a, b in sorted(spans):
        if end is None or a > end:
            total += b - a
            end = b
        elif b > end:
            total += b - end
            end = b
    return total


def _runs(boxes: Sequence[Box], items: List[int], lo: int, hi: int) -> List[Tuple[float, List[int]]]:
    """items in runs along one axis (lo, hi: the box's coordinates for it)
    that overlap one another, with the gap before each run after the first."""
    out: List[Tuple[float, List[int]]] = []
    end = None
    for k in sorted(items, key=lambda k: boxes[k][lo]):
        if end is None or boxes[k][lo] > end:
            out.append((boxes[k][lo] - end if end is not None else 0.0, [k]))
            end = boxes[k][hi]
        else:
            out[-1][1].append(k)
            end = max(end, boxes[k][hi])
    return out


def _columns(boxes: Sequence[Box], items: List[int], gutter: float) -> Optional[List[List[int]]]:
    """items in columns, left to right: cut at the gaps of gutter or more
    that run down through them all - at all of them where each column
    covers COLUMN_COVER of their height, else at the widest where its two
    sides do. None where no such gap runs."""
    runs = _runs(boxes, items, 0, 2)
    top = min(boxes[k][1] for k in items)
    height = max(boxes[k][3] for k in items) - top
    if height <= 0:
        return None

    def column(part: List[int]) -> bool:
        return _covered([(boxes[k][1], boxes[k][3]) for k in part]) >= COLUMN_COVER * height

    cuts = [i for i, (gap, _) in enumerate(runs) if i and gap >= gutter]
    if not cuts:
        return None
    parts, start = [], 0
    for i in cuts + [len(runs)]:
        parts.append([k for _, run in runs[start:i] for k in run])
        start = i
    if all(column(p) for p in parts):
        return parts
    widest = max(cuts, key=lambda i: runs[i][0])
    left = [k for _, run in runs[:widest] for k in run]
    right = [k for _, run in runs[widest:] for k in run]
    return [left, right] if column(left) and column(right) else None


def _bands(boxes: Sequence[Box], items: List[int]) -> Optional[List[List[int]]]:
    """items in two bands, upper and lower, at the widest gap running
    across them all. None where none does."""
    runs = _runs(boxes, items, 1, 3)
    if len(runs) < 2:
        return None
    widest = max(range(1, len(runs)), key=lambda i: runs[i][0])
    return [[k for _, run in runs[:widest] for k in run], [k for _, run in runs[widest:] for k in run]]


def _rows(boxes: Sequence[Box], items: List[int]) -> List[int]:
    """items row by row, top down, each row left to right: a box joins the
    row whose middle its top stands over."""
    rows: List[List[int]] = []
    for k in sorted(items, key=lambda k: boxes[k][1]):
        if rows and boxes[k][1] < sum(boxes[j][1] + boxes[j][3] for j in rows[-1]) / (2 * len(rows[-1])):
            rows[-1].append(k)
        else:
            rows.append([k])
    return [k for row in rows for k in sorted(row, key=lambda k: boxes[k][0])]
