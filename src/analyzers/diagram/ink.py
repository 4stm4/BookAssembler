"""diagram: what marks a drawing on a scanned page's pixels - no KRM access.

A page's ink falls into strokes: each a stretch of ink that holds together
- a letter, a rule, a waveform, a frame with all that is drawn onto it. A
drawing's are the long ones (STROKE) that are no rule (RULE_SPREAD) and no
mark on the text (TEXT_COVER); a figure is a drawing large enough (FIGURE,
LONG) that is no table's frame (_is_frame). Its labels are told from the
page's text by how tall their letters' ink stands (letters): a label's
print, read off a line box its drawing's strokes cross, is the strokes' as
much as its own - the Intel 3000 manual's "ED ENABLE", set 4pt, read 9.8.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.analyzers.diagram.signals import (
    FIGURE, FIGURE_ZOOM, FRAME_RULED, FRAME_SPAN, FRAME_WHOLE, INK_LEVEL, LETTERED, LINE_SPREAD, LONG, MASK_PAD,
    RULE, RULE_SPREAD, SPECK, STROKE, TEXT_COVER,
)
from src.analyzers.printed import _runs_of

Box = Tuple[float, float, float, float]


@dataclass
class PageInk:
    """A page's ink, read at FIGURE_ZOOM: each pixel's stroke (0 the
    paper) and, a row to each stroke, its box (page-normalised: x0, y0,
    x1, y1), its length - its box's longer side - and its height (pt).
    em is the page's body size (pt): what its strokes are measured by."""
    strokes: Any
    boxes: Any
    lengths: Any
    heights: Any
    page_pt: Tuple[float, float]
    em: float

    def ems(self, n: float) -> Tuple[float, float]:
        """n ems across and down, as shares of the page."""
        return (n * self.em / self.page_pt[0], n * self.em / self.page_pt[1])

    def box(self, strokes: Sequence[int]) -> Box:
        """The box about some of the page's strokes."""
        own = self.boxes[list(strokes)]
        return (float(own[:, 0].min()), float(own[:, 1].min()), float(own[:, 2].max()), float(own[:, 3].max()))

    def _pixels(self, box: Box) -> Tuple[int, int, int, int]:
        rows, cols = self.strokes.shape
        return (max(0, int(box[0] * cols)), max(0, int(box[1] * rows)),
                min(cols, int(box[2] * cols) + 1), min(rows, int(box[3] * rows) + 1))


def read_page(np, cv2, pymupdf, page: Any, em: float) -> PageInk:
    """A page's ink (a pymupdf page, its body size em) and the strokes it
    falls into."""
    pix = page.get_pixmap(matrix=pymupdf.Matrix(FIGURE_ZOOM, FIGURE_ZOOM))
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    ink = rgb.sum(axis=2, dtype=np.uint16) < 3 * INK_LEVEL
    return strokes_of(np, cv2, ink, (page.rect.width, page.rect.height), em)


def strokes_of(np, cv2, ink: Any, page_pt: Tuple[float, float], em: float) -> PageInk:
    """The strokes a page's ink (a mask read at FIGURE_ZOOM) falls into:
    ink that touches, corner to corner too, is one stroke."""
    _, strokes, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    left, top = stats[:, cv2.CC_STAT_LEFT], stats[:, cv2.CC_STAT_TOP]
    width, height = stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]
    rows, cols = ink.shape
    boxes = np.stack((left / cols, top / rows, (left + width) / cols, (top + height) / rows), axis=1)
    lengths, heights = np.maximum(width, height) / FIGURE_ZOOM, height / FIGURE_ZOOM
    lengths[0] = heights[0] = 0.0   # the paper is no stroke
    return PageInk(strokes, boxes, lengths, heights, page_pt, em)


def _letters_in(page: PageInk, box: Box) -> Any:
    """Which of the page's strokes are letters standing in a box: of a
    letter's size (SPECK to STROKE of an em), their middles in it."""
    b = page.boxes
    cx, cy = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
    return ((box[0] <= cx) & (cx <= box[2]) & (box[1] <= cy) & (cy <= box[3])
            & (page.heights >= SPECK * page.em) & (page.lengths < STROKE * page.em))


def letters(np, page: PageInk, box: Box, share: float = 90) -> float:
    """How tall the letters standing in a box are (pt): the height share
    in a hundred of them stand at or under - nine in ten of a label's few,
    its capitals' height; three in four of a line of running text's, its
    ascenders', a bracket or two over them aside. 0 where it has none."""
    own = _letters_in(page, box)
    return float(np.percentile(page.heights[own], share)) if own.any() else 0.0


def lettered(page: PageInk, box: Box) -> float:
    """The share of a box the letters standing in it cover, by their
    boxes: lines of text fill theirs, a drawing's labels stand far apart."""
    own = _letters_in(page, box)
    b = page.boxes[own]
    area = (box[2] - box[0]) * (box[3] - box[1])
    return float(((b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])).sum() / area) if area > 0 else 0.0


def drawn(np, page: PageInk, text: Sequence[Box]) -> List[int]:
    """The page's strokes that are a drawing's: STROKE ems long or more,
    clear of the page's edge - a scan's shadow reaches it - no rule, and no
    mark on text: on the page's running text (text, its boxes), or on
    lines OCR read nothing of, their letters filling the stroke's box
    (LETTERED) - a pen's underlines through the MCS-40 manual's column."""
    b = page.boxes
    clear = (b[:, 0] > 0) & (b[:, 1] > 0) & (b[:, 2] < 1) & (b[:, 3] < 1)
    return [int(k) for k in np.flatnonzero((page.lengths >= STROKE * page.em) & clear)
            if not _is_rule(np, page, int(k)) and _covered(tuple(b[k]), text) < TEXT_COVER
            and lettered(page, tuple(b[k])) < LETTERED]


def _is_rule(np, page: PageInk, stroke: int) -> bool:
    """Whether a stroke is a straight line: its ink within RULE_SPREAD of
    an em about the line through it, at whatever slant the scan has."""
    x0, y0, x1, y1 = page._pixels(tuple(page.boxes[stroke]))
    rows, cols = np.nonzero(page.strokes[y0:y1, x0:x1] == stroke)
    if len(rows) < 2:
        return True
    across = float(np.linalg.eigvalsh(np.cov(np.vstack((cols, rows))))[0])
    return max(0.0, across) ** 0.5 <= RULE_SPREAD * page.em * FIGURE_ZOOM


def _covered(box: Box, others: Sequence[Box]) -> float:
    """The share of a box that stands in others."""
    area = (box[2] - box[0]) * (box[3] - box[1])
    if area <= 0:
        return 0.0
    shared = sum(max(0.0, min(box[2], o[2]) - max(box[0], o[0])) * max(0.0, min(box[3], o[3]) - max(box[1], o[1]))
                 for o in others)
    return min(1.0, shared / area)


def is_figure(np, cv2, page: PageInk, strokes: Sequence[int]) -> bool:
    """Whether a drawing (its strokes) is a figure: FIGURE ems across and
    down or more, a stroke LONG ems long in it, and no table's frame."""
    box = page.box(strokes)
    pw, ph = page.page_pt
    if min((box[2] - box[0]) * pw, (box[3] - box[1]) * ph) < FIGURE * page.em:
        return False
    if float(page.lengths[list(strokes)].max()) < LONG * page.em:
        return False
    # the frame is judged with the rules standing in the drawing
    x0, y0, x1, y1 = page._pixels(box)
    b = page.boxes
    inside = (b[:, 0] >= box[0]) & (b[:, 1] >= box[1]) & (b[:, 2] <= box[2]) & (b[:, 3] <= box[3])
    long = inside & (page.lengths >= STROKE * page.em)
    return not _is_frame(np, cv2, long[page.strokes[y0:y1, x0:x1]].astype(np.uint8), page.em * FIGURE_ZOOM)


def _is_frame(np, cv2, mask: Any, em: float) -> bool:
    """Whether a drawing's long strokes (a mask of them, em in its pixels)
    are a table's frame: ruled across and down, its rules running its
    whole width and height."""
    reach = max(2, int(RULE * em))
    across = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((1, reach), np.uint8))
    down = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((reach, 1), np.uint8))
    # a rule's ragged edge is the rule's
    ruled = cv2.dilate(across | down, np.ones((5, 5), np.uint8))
    if int((mask & ruled).sum()) < FRAME_RULED * int(mask.sum()):
        return False
    return (_whole(np, cv2, across, em) >= FRAME_SPAN
            and _whole(np, cv2, np.ascontiguousarray(down.T), em) >= FRAME_SPAN)


def _whole(np, cv2, rules: Any, em: float) -> float:
    """Of the length of the rules running across a mask, the share on rules
    that run its whole width."""
    count, _, stats, centres = cv2.connectedComponentsWithStats(rules, connectivity=8)
    pieces = sorted((float(centres[k][1]), int(stats[k, cv2.CC_STAT_WIDTH])) for k in range(1, count))
    lines: List[List[float]] = []   # a rule's row and length, its pieces together
    for row, length in pieces:
        if lines and row - lines[-1][0] <= LINE_SPREAD * em:
            lines[-1][1] += length
        else:
            lines.append([row, length])
    total = sum(length for _, length in lines)
    if not total:
        return 0.0
    return sum(length for _, length in lines if length >= FRAME_WHOLE * rules.shape[1]) / total


def with_marks(page: PageInk, area: Box, masks: Sequence[Box], reach: Tuple[float, float]) -> Box:
    """A figure's area with the marks standing by it that are no one
    else's: strokes within reach (across, down) of the area as it grows
    over them, their middles in no mask - the boxes of the page's text. A
    ground's bars under a circuit's wire; the "OUT" at its terminal, which
    OCR read as noise. A stroke as long as a drawing's is its own only
    where it stands by it whole - a rule across the page runs on past."""
    b = page.boxes
    cx, cy = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
    free = page.lengths >= SPECK * page.em
    for m in masks:
        free &= ~((m[0] <= cx) & (cx <= m[2]) & (m[1] <= cy) & (cy <= m[3]))
    short = page.lengths < STROKE * page.em
    while True:
        x0, y0, x1, y1 = area[0] - reach[0], area[1] - reach[1], area[2] + reach[0], area[3] + reach[1]
        by = free & (b[:, 2] >= x0) & (b[:, 0] <= x1) & (b[:, 3] >= y0) & (b[:, 1] <= y1)
        by &= short | ((b[:, 0] >= x0) & (b[:, 2] <= x1) & (b[:, 1] >= y0) & (b[:, 3] <= y1))
        if not by.any():
            return area
        grown = (min(area[0], float(b[by, 0].min())), min(area[1], float(b[by, 1].min())),
                 max(area[2], float(b[by, 2].max())), max(area[3], float(b[by, 3].max())))
        if grown == area:
            return area
        area = grown


def strokes_ink(np, page: PageInk, area: Box, masks: Sequence[Box]) -> Optional[Dict[str, Any]]:
    """A figure's own ink: the page's strokes that stand in its area (to
    MASK_PAD of it) - a rule across the page, a column's rule running
    through it are not its - masks, the boxes of what in it is the page's
    text, left out. As figure_ink gives it."""
    b = page.boxes
    own = ((b[:, 0] >= area[0] - MASK_PAD) & (b[:, 1] >= area[1] - MASK_PAD)
           & (b[:, 2] <= area[2] + MASK_PAD) & (b[:, 3] <= area[3] + MASK_PAD))
    own[0] = False
    padded = (area[0] - MASK_PAD, area[1] - MASK_PAD, area[2] + MASK_PAD, area[3] + MASK_PAD)
    x0, y0, x1, y1 = page._pixels(padded)
    ink = own[page.strokes[y0:y1, x0:x1]]
    for m in masks:
        mx0, my0, mx1, my1 = page._pixels((m[0] - MASK_PAD, m[1] - MASK_PAD, m[2] + MASK_PAD, m[3] + MASK_PAD))
        ink[max(0, my0 - y0):max(0, my1 - y0), max(0, mx0 - x0):max(0, mx1 - x0)] = False
    return printed_ink(np, ink, x0 / FIGURE_ZOOM, y0 / FIGURE_ZOOM, page.page_pt)


def printed_ink(np, ink: Any, x0: float, y0: float, page_pt: Tuple[float, float]) -> Optional[Dict[str, Any]]:
    """A mask of ink read at FIGURE_ZOOM, its corner at (x0, y0) pt of its
    page, as a figure keeps it (metadata "printed_ink"): "box"
    (page-normalised, the ink's own), "shape" (rows, columns), "runs"
    ([row, first column, end column] each), "page_pt". None where there is
    none."""
    rows, cols = np.flatnonzero(ink.any(axis=1)), np.flatnonzero(ink.any(axis=0))
    if not len(rows):
        return None
    ink = ink[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    pw, ph = page_pt
    left, top = x0 + cols[0] / FIGURE_ZOOM, y0 + rows[0] / FIGURE_ZOOM
    right, bottom = x0 + (cols[-1] + 1) / FIGURE_ZOOM, y0 + (rows[-1] + 1) / FIGURE_ZOOM
    return {"box": [left / pw, top / ph, right / pw, bottom / ph], "shape": list(ink.shape),
            "runs": _runs_of(np, ink), "page_pt": [pw, ph]}
