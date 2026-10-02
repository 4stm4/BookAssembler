"""Tables drawn as boxes: a grid read off the page's pixels, not its text.

Some tables are nothing but boxes - a block diagram of coloured cells, each
holding a label, a cell running over several of its neighbours' rows or
columns (the software architecture fixture: "USER" across the top, "PR0
Function Calls" two rows deep). The text layer cannot find those: their
labels line up with nothing. The page's ink can: every cell is bounded by a
drawn line or by its fill meeting another colour, and those boundaries,
continued, make a grid.

_box_grid reads that grid: boundaries are long runs of drawn line (dark in
every channel - a green fill is dark in two, not three) or of a fill edge
(neighbouring pixels of clearly different colour, neither of them ink);
their positions, clustered, are the grid's lines; each atom of the grid
takes the median colour inside it; and atoms are joined into cells - the
largest rectangles of one colour with no boundary inside. A cell's border
flags are the sides a drawn line covers; a fill edge bounds a cell without
being a rule.
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

_BOX_ZOOM = 3.0
_DARK_LEVEL = 110            # every channel under this: drawn line or text
_MIN_BOUNDARY_PT = 15.0      # glyph strokes and their edges run shorter
_COLOUR_STEP = 150           # summed RGB difference across a fill edge
_EDGE_REACH = 3              # pixels each side a fill edge is read across
_CLUSTER_PT = 2.5            # one grid line's spread
_COVERED = 0.6               # share of a side a boundary must cover
_SAME_FILL = 90              # summed RGB difference within one fill
_PAPER_LEVEL = 235           # every channel over this: no fill
_MIN_CELLS = 4               # labelled boxes it takes to be a table

Rgb = Tuple[int, int, int]


@dataclass
class BoxCell:
    """One cell of a box grid: its place, extent on the page (pt), fill,
    and which of its sides a drawn line covers (top, right, bottom, left)."""
    row: int
    col: int
    row_span: int
    col_span: int
    rect: Tuple[float, float, float, float]
    fill: Optional[Rgb]
    ruled: Tuple[bool, bool, bool, bool]
    words: List[Any] = field(default_factory=list)


@dataclass
class BoxGrid:
    xs: List[float]
    ys: List[float]
    cells: List[BoxCell]


def _runs(np, line, min_len: int) -> List[Tuple[int, int]]:
    padded = np.concatenate(([False], line, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2]) if b - a >= min_len]


def _segments(np, mask, min_len: int) -> List[Tuple[float, int, int]]:
    """Long runs along a mask's rows, those of neighbouring rows that
    overlap joined into one: (row, start, end), the row their mean."""
    found: List[List[float]] = []          # [row sum, count, start, end, last row]
    for y, line in enumerate(mask):
        for a, b in _runs(np, line, min_len):
            for seg in found:
                if y - seg[4] <= 2 and a < seg[3] and b > seg[2]:
                    seg[0] += y
                    seg[1] += 1
                    seg[2], seg[3], seg[4] = min(seg[2], a), max(seg[3], b), y
                    break
            else:
                found.append([y, 1, a, b, y])
    return [(s[0] / s[1], int(s[2]), int(s[3])) for s in found]


def _cluster(values: List[float], spread: float) -> List[float]:
    out: List[List[float]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= spread:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def _coverage(segs: List[Tuple[float, int, int]], at: float, lo: float, hi: float, near: float) -> float:
    """Share of [lo, hi] the segments lying at `at` (within near) cover."""
    spans = sorted((max(a, lo), min(b, hi)) for p, a, b in segs if abs(p - at) <= near and b > lo and a < hi)
    covered, reach = 0.0, lo
    for a, b in spans:
        if b > reach:
            covered += b - max(a, reach)
            reach = b
    return covered / (hi - lo) if hi > lo else 0.0


def _box_grid(np, pymupdf, page) -> Optional[BoxGrid]:
    """The grid of boxes drawn on a page, or None where there is none."""
    z = _BOX_ZOOM
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z))
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(np.int16)
    dark = arr.max(axis=2) < _DARK_LEVEL
    min_len = int(_MIN_BOUNDARY_PT * z)

    # Fill edges: pixels _EDGE_REACH either side of a row (column) of
    # clearly different colours, neither of them ink. Not neighbours: a
    # scan's fill edge is blurred over a few pixels, the fixture's left
    # column of boxes - bounded by colour alone - by three.
    d = _EDGE_REACH
    step_y = (np.abs(arr[2 * d:] - arr[:-2 * d]).sum(axis=2) > _COLOUR_STEP) & ~dark[2 * d:] & ~dark[:-2 * d]
    step_x = (np.abs(arr[:, 2 * d:] - arr[:, :-2 * d]).sum(axis=2) > _COLOUR_STEP) & ~dark[:, 2 * d:] & ~dark[:, :-2 * d]
    lines_h = _segments(np, dark, min_len)
    lines_v = _segments(np, dark.T, min_len)
    bounds_h = lines_h + [(p + d, a, b) for p, a, b in _segments(np, step_y, min_len)]
    bounds_v = lines_v + [(p + d, a, b) for p, a, b in _segments(np, step_x.T, min_len)]
    if len(bounds_h) < 3 or len(bounds_v) < 3:
        return None
    near = _CLUSTER_PT * z
    ys = _cluster([p for p, _, _ in bounds_h], near)
    xs = _cluster([p for p, _, _ in bounds_v], near)
    if len(xs) < 3 or len(ys) < 3:
        return None
    nr, nc = len(ys) - 1, len(xs) - 1

    def side(segs, at, lo, hi) -> float:
        return _coverage(segs, at, lo, hi, near)

    fill = [[None] * nc for _ in range(nr)]
    for r in range(nr):
        for c in range(nc):
            y0, y1 = int(ys[r] + near), int(ys[r + 1] - near)
            x0, x1 = int(xs[c] + near), int(xs[c + 1] - near)
            if y1 <= y0 or x1 <= x0:
                continue
            block = arr[y0:y1, x0:x1].reshape(-1, 3)
            paper = block[block.max(axis=1) >= _DARK_LEVEL]
            if len(paper):
                fill[r][c] = tuple(int(v) for v in np.median(paper, axis=0))

    def same(a, b) -> bool:
        if a is None or b is None:
            return a is b
        return sum(abs(p - q) for p, q in zip(a, b)) <= _SAME_FILL

    # A boundary between atoms: a line or fill edge over most of their side.
    def open_right(r, c) -> bool:
        return side(bounds_v, xs[c + 1], ys[r], ys[r + 1]) < _COVERED and same(fill[r][c], fill[r][c + 1])

    def open_below(r, c) -> bool:
        return side(bounds_h, ys[r + 1], xs[c], xs[c + 1]) < _COVERED and same(fill[r][c], fill[r + 1][c])

    taken = [[False] * nc for _ in range(nr)]
    cells: List[BoxCell] = []
    for r in range(nr):
        for c in range(nc):
            if taken[r][c]:
                continue
            w = 1
            while c + w < nc and not taken[r][c + w] and open_right(r, c + w - 1):
                w += 1
            h = 1
            while r + h < nr and all(
                not taken[r + h][c + k] and open_below(r + h - 1, c + k) for k in range(w)
            ) and all(open_right(r + h, c + k) for k in range(w - 1)):
                h += 1
            for dr in range(h):
                for dc in range(w):
                    taken[r + dr][c + dc] = True
            x0, x1, y0, y1 = xs[c], xs[c + w], ys[r], ys[r + h]
            ruled = (
                side(lines_h, y0, x0, x1) >= _COVERED,
                side(lines_v, x1, y0, y1) >= _COVERED,
                side(lines_h, y1, x0, x1) >= _COVERED,
                side(lines_v, x0, y0, y1) >= _COVERED,
            )
            colour = fill[r][c]
            paper = colour is None or min(colour) >= _PAPER_LEVEL
            cells.append(BoxCell(r, c, h, w, (x0 / z, y0 / z, x1 / z, y1 / z), None if paper else colour, ruled))

    words = page.get_text("words")
    for cell in cells:
        x0, y0, x1, y1 = cell.rect
        cell.words = [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
    boxed = [c for c in cells if c.words and (c.fill is not None or all(c.ruled))]
    if len(boxed) < _MIN_CELLS:
        return None
    return BoxGrid([x / z for x in xs], [y / z for y in ys], cells)
