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
_MIN_CELLS = 4               # labelled boxes of colour it takes to be a table

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
    size: float = 0.0          # type size read off its first line's ink (pt)


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


_CAP_SHARE = 0.72            # capitals and ascenders over the type size
_DESCENT_SHARE = 0.21        # descenders under the baseline over it


def _ink_size(np, dark, cell: "BoxCell", z: float, inset: float) -> float:
    """A cell's type size from its first printed line: the height of the
    first band of ink rows inside it, its rules left out, over the share of
    the size its letters reach. OCR's word boxes are no measure here - on
    the fixture "Deb" was boxed over two lines and set at 16pt beside its
    neighbours' 10. 0 where there is no ink."""
    x0, y0, x1, y1 = (int(v * z) for v in cell.rect)
    pad = int(inset)
    rows = dark[y0 + pad:y1 - pad, x0 + pad:x1 - pad].any(axis=1)
    bands = _runs(np, rows, 2)
    if not bands:
        return 0.0
    a, b = bands[0]
    first_line = (sorted(cell.words, key=lambda w: w[1])[0][4] if cell.words else "")
    share = _CAP_SHARE + (_DESCENT_SHARE if any(ch in "gjpqy" for ch in first_line) else 0.0)
    return (b - a) / z / share


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
        cell.size = _ink_size(np, dark, cell, z, near)
    # Boxes of colour, not a ruled grid on paper: a ruled table's rows and
    # columns are its text's, and the text-layer detection reads them -
    # taken as boxes, the decimal/binary and pin description fixtures lost
    # their rows' own structure (6.4% -> 15.6%, 17.5% -> 23.8%).
    filled = [c for c in cells if c.words and c.fill is not None]
    if len(filled) < _MIN_CELLS:
        return None
    return BoxGrid([x / z for x in xs], [y / z for y in ys], cells)


def _cell_lines(words: List[Any]) -> str:
    """A cell's words as its printed lines, top to bottom, each left to right."""
    lines: List[List[Any]] = []
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        centre = (w[1] + w[3]) / 2
        if lines and abs(centre - sum((v[1] + v[3]) / 2 for v in lines[-1]) / len(lines[-1])) < 0.5 * (w[3] - w[1]):
            lines[-1].append(w)
        else:
            lines.append([w])
    return "\n".join(" ".join(v[4] for v in sorted(line, key=lambda v: v[0])) for line in lines)


def _table_from_box_grid(grid: BoxGrid, page_idx: int, pw: float, ph: float) -> "TableBlock":
    """A TableBlock of a box grid: a row per grid row holding the cells
    that start in it, each spanning what it covers, with its fill, its
    drawn sides and its place in the grid (metadata grid_row / grid_col),
    which says more than its box: a spanning cell's box is centred over
    columns it does not start in."""
    from src.krm.models import (
        NormalizedRect, ParagraphBlock, StyledTextSpan, StyleDescriptor, TableBlock, TableCell,
        TextLineInline, VisualLayout,
    )
    rows: List[List[TableCell]] = [[] for _ in range(len(grid.ys) - 1)]
    span_map = {}
    for box in sorted(grid.cells, key=lambda b: (b.row, b.col)):
        x0, y0, x1, y1 = box.rect
        style = StyleDescriptor(font_size_pt=box.size, background_color_rgb=box.fill)
        cell = TableCell(
            row_span=box.row_span,
            col_span=box.col_span,
            content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=_cell_lines(box.words))])])],
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(x0=x0 / pw, y0=y0 / ph, x1=x1 / pw, y1=y1 / ph),
                page_or_screen_index=page_idx, style=style,
            ),
            border_top=box.ruled[0], border_right=box.ruled[1],
            border_bottom=box.ruled[2], border_left=box.ruled[3],
        )
        cell.metadata["grid_row"], cell.metadata["grid_col"] = box.row, box.col
        rows[box.row].append(cell)
        for r in range(box.row, box.row + box.row_span):
            for c in range(box.col, box.col + box.col_span):
                if (r, c) != (box.row, box.col):
                    span_map[(r, c)] = (box.row, box.col)
    xs, ys = grid.xs, grid.ys
    table = TableBlock(
        grid=rows,
        row_count=len(rows),
        column_count=len(xs) - 1,
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=xs[0] / pw, y0=ys[0] / ph, x1=xs[-1] / pw, y1=ys[-1] / ph),
            page_or_screen_index=page_idx,
        ),
        span_map=span_map,
    )
    table.metadata.update({
        "box_grid": True,
        "column_rule_x": [x / pw for x in xs[1:-1]],
        "rule_y": [y / ph for y in ys],
        "table_rule_x0": xs[0] / pw, "table_rule_x1": xs[-1] / pw,
        "table_rule_y0": ys[0] / ph, "table_rule_y1": ys[-1] / ph,
    })
    return table
