"""register: what marks a register on a page's pixels - no KRM access.

A register is drawn as a frame - two rules of one length, joined at both
ends - its cells marked off by short ticks down from its top rule and up
from its bottom one, evenly: "1 1 0 1 1 1 0 1" under PUSH IX in the Z80
manual (the paragraph fixture C). Its ticks are no full rules, so the box
grids (table/boxes.py) do not see its cells.
"""

from dataclasses import dataclass
from typing import Any, List

from src.analyzers.table.boxes import _segments

ZOOM = 3.0
_DARK_LEVEL = 110          # every channel under this: drawn line or text
_MIN_WIDTH_PT = 30.0       # a register's rules are longer than this
_HEIGHT_PT = (6.0, 40.0)   # and stand this far apart
_EDGE_PT = 2.0             # how far apart the rules' ends may be
_SIDE_COVER = 0.8          # of the height, a side's rule covers
_RULE_COVER = 0.8          # of its length, a row of a rule is inked
_TICK = (0.1, 0.45)        # of the height, how long a tick runs in from its rule
_TICK_MERGE_PT = 2.0       # a top tick and a bottom one this close mark one edge
_EVEN = 0.25               # the most the cells' widths spread over their mean
_MIN_CELLS = 3


@dataclass
class Register:
    """A frame on a page (pt): its rules' rows, its sides, the cells'
    edges along it (both sides included) and how far its ticks run in."""
    x0: float
    y0: float
    x1: float
    y1: float
    cuts: List[float]
    tick: float


def register_frames(np, dark) -> List[Register]:
    """The registers drawn on a page's dark pixels (rendered at ZOOM)."""
    z = ZOOM
    rules = sorted(_segments(np, dark, int(_MIN_WIDTH_PT * z)), key=lambda s: s[0])
    found: List[Register] = []
    for i, (top, a, b) in enumerate(rules):
        for bottom, a2, b2 in rules[i + 1:]:
            height = bottom - top
            if height < _HEIGHT_PT[0] * z:
                continue
            if height > _HEIGHT_PT[1] * z:
                break
            if abs(a - a2) > _EDGE_PT * z or abs(b - b2) > _EDGE_PT * z:
                continue
            frame = _read_frame(np, dark, int(round(top)), int(round(bottom)), int(max(a, a2)), int(min(b, b2)))
            if frame is not None:
                found.append(frame)
                break
    return found


def _read_frame(np, dark, top: int, bottom: int, left: int, right: int):
    z = ZOOM
    height = bottom - top
    reach = max(2, int(_EDGE_PT * z))

    def side(x: int) -> bool:
        cols = dark[top:bottom + 1, max(0, x - reach):x + reach + 1]
        return cols.size > 0 and cols.any(axis=1).mean() >= _SIDE_COVER

    if not side(left) or not side(right):
        return None
    inner = slice(left + reach + 1, right - reach)
    top_rows = [r for r in range(top - reach, top + reach + 1) if dark[r, inner].mean() >= _RULE_COVER]
    bottom_rows = [r for r in range(bottom - reach, bottom + reach + 1) if dark[r, inner].mean() >= _RULE_COVER]
    if not top_rows or not bottom_rows:
        return None
    under, over = max(top_rows) + 1, min(bottom_rows) - 1
    lo, hi = int(_TICK[0] * height), int(_TICK[1] * height)
    ticks: List[float] = []
    longest = 0
    run: List[int] = []
    for c in range(left + reach + 1, right - reach):
        down = 0
        while under + down < over and dark[under + down, c]:
            down += 1
        up = 0
        while over - up > under and dark[over - up, c]:
            up += 1
        if lo <= down <= hi or lo <= up <= hi:
            run.append(c)
            longest = max(longest, down if down <= hi else 0, up if up <= hi else 0)
        elif run:
            ticks.append(sum(run) / len(run))
            run = []
    if run:
        ticks.append(sum(run) / len(run))
    merged: List[float] = []
    for t in ticks:
        if merged and t - merged[-1] <= _TICK_MERGE_PT * z:
            merged[-1] = (merged[-1] + t) / 2
        else:
            merged.append(t)
    cuts = [float(left)] + merged + [float(right)]
    widths = [b - a for a, b in zip(cuts, cuts[1:])]
    if len(widths) < _MIN_CELLS:
        return None
    mean = sum(widths) / len(widths)
    if max(abs(w - mean) for w in widths) > _EVEN * mean:
        return None
    return Register(left / z, top / z, right / z, bottom / z, [c / z for c in cuts], longest / z)


def bits_of(words: List[Any], register: Register) -> Any:
    """The word a register's bits were read as: of the words inside its
    frame, the one with a character to each cell - the ticks come through
    as stray letters beside it. None where none fits."""
    cells = len(register.cuts) - 1
    inside = [w for w in words
              if register.x0 <= (w[0] + w[2]) / 2 <= register.x1 and register.y0 <= (w[1] + w[3]) / 2 <= register.y1]
    fitting = [w for w in inside if len(w[4].strip()) == cells]
    return max(fitting, key=lambda w: w[2] - w[0]) if fitting else None
