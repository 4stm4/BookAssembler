"""table: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.table.signals import MAX_BLOCK_HEIGHT, MAX_CELL_TEXT_LEN, MIN_TABLE_ROWS, X_OVERLAP_THRESHOLD, Y_STEP_TOLERANCE, _SEPARATOR_RE, _SINGLE_COL_PROSE_LEN, _TAB_SPLIT_RE, log
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TableBlock,
    TableCell,
    TextLineInline,
    VisualLayout,
)

_RULE_ZOOM = 3.0          # render scale for rule detection
_RULE_PAD_PT = 20.0       # printed rules sit outside the cells' own text boxes
# 12.0 was not enough to reach a table's OUTER rules, only its internal
# ones: measured directly on RFC 0001 SS2.4's decimal/binary fixture, that
# table's left rule sits 13.9pt outside its own bounding box (165.4pt vs
# bbox.x0 at 179.3pt) - the box being the union of the CELLS' boxes, a
# text extent, which a right-aligned column's glyphs never fill out to
# the rule. Scanning a strip 30pt wide on each side of both fixtures
# found nothing but those tables' own rules, so reaching further does
# not risk sweeping in a neighbour's.
_RULE_INK_LEVEL = 160     # 0-255 grey below which a pixel counts as ink
_RULE_SPAN = 0.60         # a rule crosses most of the table, text never does

# Smallest reach allowed when asking whether a horizontal rule runs along a
# cell's own edge. The reach is normally the cell's own height, which is the
# right scale and needs no table-wide constant; this only covers a cell whose
# box came out with no height at all, so that it does not silently match
# every line on the page.
_BORDER_MATCH_FLOOR = 0.001


def _rule_runs(flags) -> List[Tuple[int, int]]:
    """Contiguous True spans in a 1-D boolean array (one per printed rule)."""
    out: List[Tuple[int, int]] = []
    start = None
    for i, value in enumerate(flags):
        if value and start is None:
            start = i
        elif not value and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(flags)))
    return out


def _mark_cell_borders(np, pymupdf, page, table) -> bool:
    """Set each cell's border_* from the rules printed on the source page.

    These pages are scans: the rules are not vector strokes the adapter
    could have carried into the KRM (page.get_drawings() finds none), so
    the rendered image is the only place they exist. A rule is the one
    thing in a table region that runs across most of its width or height -
    text never does - so thresholding the region and asking which pixel
    rows/columns are almost entirely ink finds them without needing to know
    where the columns are.

    Each cell is then asked about its own four edges: a cell carries a
    border where a detected line runs along that edge of its box. Storing
    it per cell rather than as a table-level summary keeps the one thing a
    summary throws away - which particular edge was drawn.

    Returns True when at least one border was set.
    """
    bbox = table.visual_layout.bounding_box
    page_w, page_h = page.rect.width, page.rect.height
    clip = pymupdf.Rect(
        bbox.x0 * page_w - _RULE_PAD_PT, bbox.y0 * page_h - _RULE_PAD_PT,
        bbox.x1 * page_w + _RULE_PAD_PT, bbox.y1 * page_h + _RULE_PAD_PT,
    )
    clip = clip & page.rect
    if clip.is_empty or clip.width < 2 or clip.height < 2:
        return None

    pix = page.get_pixmap(matrix=pymupdf.Matrix(_RULE_ZOOM, _RULE_ZOOM), clip=clip)
    if pix.width < 2 or pix.height < 2:
        return None
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < _RULE_INK_LEVEL
    height, width = ink.shape

    horizontal = _rule_runs(ink.sum(axis=1) > _RULE_SPAN * width)
    vertical = _rule_runs(ink.sum(axis=0) > _RULE_SPAN * height)
    if not horizontal and not vertical:
        return False

    # Each run is a band of pixels in the crop; its centre, taken back
    # through the render scale and the crop's own offset, is where the
    # printed line sits on the page.
    def to_page(run: Tuple[int, int], origin: float, extent: float) -> float:
        centre = (run[0] + run[1]) / 2.0
        return (origin + centre / _RULE_ZOOM) / extent

    rule_x = [to_page(run, clip.x0, page_w) for run in vertical]
    rule_y = [to_page(run, clip.y0, page_h) for run in horizontal]

    # The INTERNAL vertical rules - the ones strictly between the table's
    # own left and right edges - are the real column boundaries the
    # source actually drew, in the same page-fraction units the rest of
    # this pipeline uses. A cell's own text extent is not this: a
    # right-aligned "120" in a column drawn 2cm wide only occupies the
    # right half of it, and measuring from glyphs alone (tried in
    # src/assembler/latex_builder.py) systematically undersizes exactly
    # that kind of column. _RULE_PAD_PT's search margin means a table's
    # OUTER edges sometimes get detected too, just outside bbox.x0/x1 -
    # excluding anything not strictly inside the table's own box is what
    # keeps only the boundaries BETWEEN columns.
    internal_rule_x = sorted(x for x in rule_x if bbox.x0 < x < bbox.x1)

    # The table's own OUTER rules, when it drew any: the nearest rule at
    # or beyond each edge of its box. These were detected all along (the
    # search pad reaches past the box on purpose) and then dropped,
    # leaving src/assembler/latex_builder.py to substitute bbox.x0/bbox.x1
    # for them when it splits the table into columns. That substitution is
    # not like-for-like: every INTERNAL boundary it uses is a real printed
    # rule, while the two outer ones came from the box, which is the union
    # of the CELLS' boxes - a TEXT extent. A column's glyphs never reach
    # its rule (a right-aligned number sits against one edge only), so the
    # error landed entirely on the first and last column. Measured on RFC
    # 0001 SS2.4's decimal/binary fixture: 13.9pt of real width missing on
    # the left, 7.6pt on the right, while both INTERNAL columns came out
    # within 1.3pt of the source.
    #
    # Not every table has them - the voltage-regulator fixture draws no
    # outer rules at all (its rightmost column has no right edge printed,
    # confirmed by scanning 30pt past the box on both sides and finding
    # only that table's five internal rules), so this stays optional and
    # that table keeps using its box, exactly as before.
    outer_left = max((x for x in rule_x if x <= bbox.x0), default=None)
    outer_right = min((x for x in rule_x if x >= bbox.x1), default=None)

    # How far each column's own ink actually sits from its rules. The
    # assembler needs this to reproduce the indent the source printed
    # (LaTeX otherwise sets every column exactly \tabcolsep from its
    # rule, while this fixture's columns are indented 5.2-8.2pt), and it
    # CANNOT derive it from the KRM cell boxes: measured against the
    # pixels, a per-column median of those boxes is off by 33-39pt on a
    # right-set column (each row's number has its own digit count, so the
    # ragged side is not stable) and comes out NEGATIVE on another, since
    # some cells' boxes cross a rule outright. Ink is the only honest
    # source, and this function already has it rendered.
    _bands = (
        [outer_left if outer_left is not None else bbox.x0]
        + internal_rule_x
        + [outer_right if outer_right is not None else bbox.x1]
    )
    ink_x0: List[Optional[float]] = []
    ink_x1: List[Optional[float]] = []
    # Horizontal rules have to come out of this first. A rule inks EVERY
    # pixel column it crosses, so asking "does this column have any ink"
    # over the raw band answers yes everywhere and the measurement
    # collapses onto whatever margin is kept clear of the vertical rules
    # - measured, it returned a flat 1.3-1.7pt for every column of both
    # fixtures, where the real indents range 5.2-19.9pt.
    _row_keep = np.ones(height, dtype=bool)
    for _r0, _r1 in horizontal:
        _row_keep[_r0:_r1 + 1] = False
    # "Any ink at all in this pixel column" is useless on a scan: a
    # speckle lands in practically every column, so the first inked
    # column is always the very first one and the measurement collapses
    # onto whatever margin is kept clear of the rules (it returned a flat
    # 1.3-1.7pt for every column of both fixtures). Profiled on the
    # decimal/binary fixture's first column band, the separation is
    # wide and unambiguous: noise sits at a median of 12 inked rows per
    # column, real glyph columns reach 425, and requiring 1% of the
    # band's rows puts the first content at 13.67pt where an
    # independent word-box measurement says 13.7. 1.5% is taken rather
    # than 1% to stand clear of that noise median on dirtier scans; it
    # costs about 0.3pt against indents that run 3.6-6.6pt.
    _rows_kept = ink[_row_keep] if _row_keep.any() else ink
    _MIN_INK_ROW_SHARE = 0.015
    _col_ink_rows = _rows_kept.sum(axis=0)
    _inked_cols = _col_ink_rows > (_MIN_INK_ROW_SHARE * max(1, _rows_kept.shape[0]))
    for _i in range(len(_bands) - 1):
        # Keep clear of both rules so their own pixels are not read as
        # the column's content. 1.5pt was not enough: profiled on the
        # decimal/binary fixture, a printed rule is about 10px wide at
        # this zoom (~3.3pt, so ~1.7pt each side of the position stored
        # for it), and the leading flank landed inside the old margin -
        # three of that table's four columns then reported their right
        # padding as exactly the margin (1.5pt) instead of the real
        # 5.6/8.2/11.8pt, because the rule itself was being read as the
        # column's own ink. The fourth only escaped because it happens
        # to have 19pt of clear space before its rule.
        _RULE_CLEARANCE_PT = 3.0
        _lo = int(((_bands[_i] * page_w + _RULE_CLEARANCE_PT) - clip.x0) * _RULE_ZOOM)
        _hi = int(((_bands[_i + 1] * page_w - _RULE_CLEARANCE_PT) - clip.x0) * _RULE_ZOOM)
        _lo = max(0, min(width - 1, _lo))
        _hi = max(0, min(width, _hi))
        if _hi <= _lo:
            ink_x0.append(None)
            ink_x1.append(None)
            continue
        _cols = np.nonzero(_inked_cols[_lo:_hi])[0]
        if _cols.size == 0:
            ink_x0.append(None)
            ink_x1.append(None)
            continue
        ink_x0.append((clip.x0 + (_lo + int(_cols[0])) / _RULE_ZOOM) / page_w)
        ink_x1.append((clip.x0 + (_lo + int(_cols[-1]) + 1) / _RULE_ZOOM) / page_w)

    if internal_rule_x or outer_left is not None or outer_right is not None:
        md = getattr(table, "metadata", None)
        if md is None:
            md = {}
            table.metadata = md
        if internal_rule_x:
            md["column_rule_x"] = internal_rule_x
        if outer_left is not None:
            md["table_rule_x0"] = outer_left
        if outer_right is not None:
            md["table_rule_x1"] = outer_right
        if any(v is not None for v in ink_x0):
            md["column_ink_x0"] = ink_x0
            md["column_ink_x1"] = ink_x1

    placed = [
        cell for row in table.grid for cell in row
        if cell.visual_layout is not None and cell.visual_layout.bounding_box is not None
    ]
    if not placed:
        return False

    # The printed lines ARE the grid - there is no need to infer columns
    # from where the glyphs happen to start, which is what an earlier
    # version did and what kept going wrong (the spread inside one column
    # is larger than the distance used to separate columns, so four columns
    # clustered into sixteen tracks and a shared boundary came back ruled
    # on one side only). A cell simply sits in the band between two lines.
    verticals = sorted(rule_x)
    horizontals = sorted(rule_y)
    if not verticals and not horizontals:
        return False

    def band(position: float, lines: List[float]) -> Tuple[Optional[float], Optional[float]]:
        before = [v for v in lines if v <= position]
        after = [v for v in lines if v >= position]
        return (before[-1] if before else None, after[0] if after else None)

    for cell in placed:
        box = cell.visual_layout.bounding_box
        # A vertical rule runs the full height of the table, so the lines
        # bounding a cell's band are that column's edges for every cell in
        # it - no proximity test needed or wanted.
        left, right = band((box.x0 + box.x1) / 2.0, verticals)
        cell.border_left = left is not None
        cell.border_right = right is not None

        # A horizontal rule spans the full width the same way, but a table
        # ruled only under its header puts 22 rows inside one band, and the
        # rows in the middle of it touch neither line. So an edge counts
        # only when the line actually runs along it, judged against this
        # cell's own height rather than any table-wide constant.
        above, below = band((box.y0 + box.y1) / 2.0, horizontals)
        reach = max(box.y1 - box.y0, _BORDER_MATCH_FLOOR)
        cell.border_top = above is not None and (box.y0 - above) <= reach
        cell.border_bottom = below is not None and (below - box.y1) <= reach
    return True


def _looks_like_separator(text: str) -> bool:
    return bool(_SEPARATOR_RE.match(text.strip()))

def _count_columns(text: str) -> int:
    parts = _TAB_SPLIT_RE.split(text.strip())
    return len([p for p in parts if p.strip()])

def _get_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)

def _bbox(block: ParagraphBlock) -> Optional[NormalizedRect]:
    vl = getattr(block, "visual_layout", None)
    if vl is None:
        return None
    return getattr(vl, "bounding_box", None)

def _page_idx(block: ParagraphBlock) -> Optional[int]:
    vl = getattr(block, "visual_layout", None)
    if vl is None:
        return None
    return getattr(vl, "page_or_screen_index", None)

def _x_overlaps(a: NormalizedRect, b: NormalizedRect) -> bool:
    overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
    width = min(a.x1 - a.x0, b.x1 - b.x0)
    if width <= 0:
        return False
    return overlap / width >= X_OVERLAP_THRESHOLD

_ROW_GROUP_TOLERANCE = 0.003  # matches _ROW_Y_TOLERANCE below - same "one visual row" test


def _group_column_by_row(
    blocks_with_idx: List[Tuple[int, ParagraphBlock]],
) -> List[List[Tuple[int, ParagraphBlock]]]:
    """Group column-clustered SIBLING blocks sharing a y0 into one visual row.

    _cluster_columns bands blocks by x-overlap, but a real table row's own
    label and its condition/value text are often themselves separate PDF
    blocks whose x-ranges both fall inside the SAME wide x-band (a table's
    "label" and "condition" sub-columns overlap in x range across
    different rows, so _cluster_columns can't tell them apart as two bands)
    - two or more blocks then land side by side at nearly the same y0
    within one column cluster, not stacked as separate rows (found on the
    messy voltage-regulator fixture: "Output Voltage" / "5mA<l0UT<1JOA
    K15W" / "114 124 V" sit 0.0003-0.0004 apart in y0, one visual row split
    across three sibling blocks). Treating each as its own row let the
    y-step "continue if two rows are basically at the same y0" guard in
    the run-builder below silently DROP every block after the first at
    that y0 instead of keeping them - RFC 0001 SS2.4 exists for exactly
    this kind of silent loss.
    """
    sorted_blocks = sorted(blocks_with_idx, key=lambda t: _bbox(t[1]).y0)
    groups: List[List[Tuple[int, ParagraphBlock]]] = []
    for item in sorted_blocks:
        y0 = _bbox(item[1]).y0
        if groups and abs(y0 - _bbox(groups[-1][0][1]).y0) < _ROW_GROUP_TOLERANCE:
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def _find_table_runs(
    blocks_with_idx: List[Tuple[int, ParagraphBlock]],
) -> List[List[List[Tuple[int, ParagraphBlock]]]]:
    """Find runs of visual ROWS (each row possibly several sibling blocks)
    with consistent vertical spacing. Each element of a returned run is a
    row-group from _group_column_by_row, not a single block."""
    groups = _group_column_by_row(blocks_with_idx)
    if len(groups) < MIN_TABLE_ROWS:
        return []

    def gy0(group: List[Tuple[int, ParagraphBlock]]) -> float:
        return _bbox(group[0][1]).y0

    runs: List[List[List[Tuple[int, ParagraphBlock]]]] = []
    current_run: List[List[Tuple[int, ParagraphBlock]]] = [groups[0]]
    current_step: Optional[float] = None

    for i in range(1, len(groups)):
        step = gy0(groups[i]) - gy0(groups[i - 1])

        if step < 0.005:
            continue

        if current_step is None:
            current_step = step
            current_run.append(groups[i])
        elif abs(step - current_step) < Y_STEP_TOLERANCE:
            current_run.append(groups[i])
        else:
            if len(current_run) >= MIN_TABLE_ROWS:
                runs.append(current_run)
            current_run = [groups[i]]
            current_step = None

    if len(current_run) >= MIN_TABLE_ROWS:
        runs.append(current_run)

    return runs


def _rows_from_group(group: List[Tuple[int, Any]]) -> List[List["TableCell"]]:
    """One visual row's worth of grid rows, from one or more sibling blocks.

    A singleton group (the common case) is just one block - defer to
    _rows_from_block, which already knows how to split ITS OWN internal
    lines into columns and detect a real rowspan within them. A group of
    several sibling blocks sharing a y0 (see _group_column_by_row) merges
    all of their line-fragments by x0 into one row instead - each block
    already carries its own column position, geometry, and font.
    """
    if len(group) == 1:
        return _rows_from_block(group[0][1])

    fragments: List[Tuple[str, Optional[NormalizedRect], Optional[Any]]] = []
    # Which sibling block each fragment's bbox came from, keyed by the
    # bbox object's own identity - _group_into_rows and _make_cell both
    # keep passing (text, bbox, style) triples around unchanged, so this
    # side table is how a fragment's origin block survives the trip
    # without widening that shared tuple shape everywhere it is unpacked.
    # Needed for the same reason _rows_from_block now tags its own cells:
    # a fragment split off into its own grid row for having no sibling
    # value at its y0 (see _merge_orphan_rows) still came from the same
    # source block as another fragment that DID land in a full row, and
    # that fact should settle where it belongs instead of a y0-distance
    # guess.
    fragment_block_id: Dict[int, str] = {}
    page_idx = None
    for _, block in group:
        page_idx = page_idx or _page_idx(block)
        block_id = getattr(block, "id", None)
        for item in _line_rows(block):
            if _looks_like_separator(item[0]):
                continue
            fragments.append(item)
            if item[1] is not None and block_id is not None:
                fragment_block_id[id(item[1])] = block_id

    if not fragments:
        cells = [
            _make_cell(_get_text(block), None, None, None, source_block_id=getattr(block, "id", None))
            for _, block in sorted(group, key=lambda t: (_bbox(t[1]).x0 if _bbox(t[1]) else 0.0))
        ]
        return [cells]

    sub_rows = _group_into_rows(fragments)
    return [
        [
            _make_cell(t, b, s, page_idx, source_block_id=fragment_block_id.get(id(b)) if b is not None else None)
            for t, b, s in row
        ]
        for row in sub_rows
    ]

def _line_rows(block: Any) -> List[Tuple[str, Optional[NormalizedRect], Optional[Any]]]:
    """Per-line (text, bbox, style) triples from a block's own inlines.

    PdfSourceAdapter keeps each source line's own bounding box AND
    StyleDescriptor (font family, size, bold/italic/mono) on its inline
    (RFC 0008 §5.2: it groups visually-contiguous text into one block
    without splitting it, but does not discard line geometry or typography),
    so a block that itself contains several table-row-shaped lines can be
    read as row candidates — width, height and font included — without
    every row needing to be a separate sibling.
    """
    rows: List[Tuple[str, Optional[NormalizedRect], Optional[Any]]] = []
    for inline in (block.inlines or []):
        text = "".join(
            span.text for span in getattr(inline, "spans", [])
            if hasattr(span, "text")
        ).strip()
        if not text:
            continue
        vl = getattr(inline, "visual_layout", None)
        bbox = getattr(vl, "bounding_box", None) if vl else None
        style = getattr(vl, "style", None) if vl else None
        rows.extend(_split_numeric_pair(text, bbox, style))
    return rows


def _split_numeric_pair(
    text: str, bbox: Optional[NormalizedRect], style: Optional[Any],
) -> List[Tuple[str, Optional[NormalizedRect], Optional[Any]]]:
    """Split "63 00111111" into "63" and "00111111", each with its own bbox.

    PyMuPDF's own line grouping is inconsistent row to row on this exact
    table: most rows keep a decimal value and its binary value as separate
    PDF lines (two inlines, two bboxes, cleanly binned to two columns), but
    some rows fuse them into one inline whose bbox spans both columns'
    width. Binning that fused fragment by its own x0 alone drops it whole
    into one column and leaves the other blank for that row - visually, the
    binary value reads as printed under the Decimal heading.

    Narrowly scoped on purpose: only fires when every whitespace-separated
    token is pure digits (a page of running text never matches this), so a
    real multi-word label ("Line Regulation") is never touched. Width is
    split proportionally by character count - the source uses a fixed-width
    face for these numbers, so this lines the split up with the real glyph
    boundaries closely enough for column binning.
    """
    tokens = text.split()
    if len(tokens) < 2 or not all(t.isdigit() for t in tokens):
        return [(text, bbox, style)]
    if bbox is None:
        return [(text, bbox, style)]
    total_chars = sum(len(t) for t in tokens)
    if total_chars == 0:
        return [(text, bbox, style)]
    width = bbox.x1 - bbox.x0
    parts: List[Tuple[str, Optional[NormalizedRect], Optional[Any]]] = []
    x = bbox.x0
    for i, tok in enumerate(tokens):
        share = len(tok) / total_chars
        tok_width = width * share
        x1 = bbox.x1 if i == len(tokens) - 1 else min(bbox.x1, x + tok_width)
        parts.append((tok, NormalizedRect(x0=x, y0=bbox.y0, x1=x1, y1=bbox.y1), style))
        x = x1
    return parts


def _make_cell(
    text: str, bbox: Optional[NormalizedRect], style: Optional[Any],
    page_idx: Optional[int], row_span: int = 1,
    source_block_id: Optional[str] = None,
) -> "TableCell":
    cell = TableCell(
        row_span=row_span,
        content=[ParagraphBlock(
            inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        )],
        visual_layout=VisualLayout(
            bounding_box=bbox, page_or_screen_index=page_idx or 0, style=style,
        ) if bbox is not None else None,
    )
    # Which source PdfSourceAdapter block this cell's text came from - a
    # block whose own lines land in different grid rows (_group_into_rows
    # splits them apart by y0 whenever nothing else lines up beside them,
    # e.g. a condition cell's trailing line with no sibling MIN/TYP/MAX
    # value of its own) still came from the SAME printed paragraph as its
    # sibling lines. _merge_orphan_rows uses this to recognize that link
    # directly instead of only guessing it back from y0 proximity, which
    # cannot tell a trailing continuation of the row above it apart from
    # a leading continuation of the row below (RFC 0001 SS2.4's "P<15W"
    # fixture: nearest-by-y0 alone ties 0.0088 vs 0.0104 between the two
    # and picks the wrong one).
    if source_block_id is not None:
        cell.metadata["source_block_id"] = source_block_id
    return cell


def _local_column_bins(
    fragments: List[Tuple[str, Optional[NormalizedRect], Optional[Any]]],
    tolerance: float = 0.02,
) -> List[float]:
    x0s = sorted(b.x0 for _, b, _ in fragments if b is not None)
    bins: List[float] = []
    for x in x0s:
        if bins and x - bins[-1] < tolerance:
            continue
        bins.append(x)
    return bins


def _nearest_bin(x0: float, bins: List[float]) -> int:
    return min(range(len(bins)), key=lambda i: abs(bins[i] - x0))


def _rows_from_block(block: Any) -> List[List["TableCell"]]:
    """Split one sibling block's own lines into column-ordered grid rows.

    The cross-block path (_find_table_runs) treats each sibling block as one
    table row. That block's own inlines carry the same per-line geometry
    _table_from_lines reads for a single-block table (RFC 0008 §5.2: the
    adapter groups text into blocks without splitting it, but keeps each
    line's own bbox and StyleDescriptor) - sorting those fragments by x0
    recovers the real column order instead of joining everything into one
    cell.

    A block can itself contain more than one visual sub-row sharing a
    single logical table row (e.g. "Line Regulation" / "Tj - 25*C" printed
    once, next to two stacked condition lines each with their own MIN/TYP
    value) - a real rowspan, not a second table row. A column populated in
    only the first sub-row and blank in the rest becomes one TableCell with
    row_span set to the sub-row count, held in the first output row only;
    later output rows simply have no cell at that column, which is exactly
    how a jagged row already renders (RFC 0002: TableCell.row_span existed
    but nothing ever set it).

    A block with no per-line geometry (or none of it survives filtering)
    falls back to a single row holding the whole block's text.
    """
    fragments = [item for item in _line_rows(block) if not _looks_like_separator(item[0])]
    block_id = getattr(block, "id", None)
    if not fragments:
        text = _get_text(block)
        return [[_make_cell(text, None, None, None, source_block_id=block_id)]]

    page_idx = _page_idx(block)
    sub_rows = _group_into_rows(fragments)

    if len(sub_rows) <= 1:
        row = sub_rows[0] if sub_rows else fragments
        row = sorted(row, key=lambda item: item[1].x0 if item[1] is not None else 0.0)
        return [[_make_cell(t, b, s, page_idx, source_block_id=block_id) for t, b, s in row]]

    # A real rowspan needs the LATER sub-rows to be genuine multi-column data
    # rows continuing this one, not just the next unrelated line of prose
    # that happens to share this block (e.g. a title line "jiA7812" directly
    # above an unrelated paragraph line - one fragment each, nothing in
    # common). Require every sub-row after the first to carry at least 2
    # fragments of its own before treating a first-row-only column as shared.
    looks_like_continuation = all(len(r) >= 2 for r in sub_rows[1:])

    # Sub-rows of equal length are parallel rows, not a label with the rows
    # it spans. A block often holds a table's heading line and its first
    # data line together, and those two never start at the same x - the
    # heading sits over the column, the value sits where the digits begin -
    # so binning by x puts them in different columns, every column comes
    # back occupied by exactly one sub-row, and the whole rowspan mechanism
    # fires on a row that shares nothing. That is where the \multirow struck
    # through the CONDITIONS heading came from. When the sub-rows have the
    # same number of fragments there is nothing to span: the nth fragment of
    # each is the nth column.
    widths = {len(r) for r in sub_rows}
    parallel_rows = len(widths) == 1

    # column index -> {sub_row index -> (text, bbox, style)}
    by_col: Dict[int, Dict[int, Tuple[str, Optional[NormalizedRect], Optional[Any]]]] = {}
    if parallel_rows:
        for sr_idx, sub_row in enumerate(sub_rows):
            ordered = sorted(
                sub_row, key=lambda item: item[1].x0 if item[1] is not None else 0.0
            )
            for col, (text, bbox, style) in enumerate(ordered):
                by_col.setdefault(col, {})[sr_idx] = (text, bbox, style)
    else:
        bins = _local_column_bins(fragments)
        for sr_idx, sub_row in enumerate(sub_rows):
            for text, bbox, style in sub_row:
                col = _nearest_bin(bbox.x0, bins) if bbox is not None else 0
                by_col.setdefault(col, {})[sr_idx] = (text, bbox, style)

    rows: List[List[TableCell]] = [[] for _ in sub_rows]
    for col in sorted(by_col):
        occupied = by_col[col]
        is_rowspan_col = len(occupied) == 1 and len(sub_rows) > 1 and looks_like_continuation and (
            0 in occupied
            # With only two sub-rows, a column populated in sub-row 1 alone
            # is usually the OTHER kind of block this same path reads: one
            # header line plus one data line, where a data-only field
            # (e.g. "Tj - 25*C") must stay on its own row, not be promoted
            # into the header as a false rowspan. That ambiguity needs a
            # third sub-row to resolve, so only 3+ sub-rows allow the label
            # to sit anywhere but first - a vertically-centered label really
            # can print between the condition rows it covers rather than
            # above both of them (found on the messy voltage-regulator
            # fixture: "Load Regulation"/"Tj - 25*C" sits between its two
            # condition rows' y0s, not above them).
            or len(sub_rows) >= 3
        )
        if is_rowspan_col:
            (sr_idx, (text, bbox, style)), = occupied.items()
            rows[0].append(_make_cell(
                text, bbox, style, page_idx, row_span=len(sub_rows), source_block_id=block_id,
            ))
            continue
        for sr_idx in sorted(occupied):
            text, bbox, style = occupied[sr_idx]
            rows[sr_idx].append(_make_cell(text, bbox, style, page_idx, source_block_id=block_id))

    for row in rows:
        row.sort(key=lambda c: c.visual_layout.bounding_box.x0 if c.visual_layout else 0.0)

    # A sub-row whose only content was a label now folded into another row's
    # rowspan (rows[0]) has nothing left of its own - a real jagged row from
    # the source never comes out fully empty, so this is purely the rowspan
    # merge's bookkeeping and would otherwise show up as a blank grid row.
    return [row for row in rows if row]


_ROW_Y_TOLERANCE = 0.003


def _group_into_rows(
    rows: List[Tuple[str, Optional[NormalizedRect], Optional[Any]]],
) -> List[List[Tuple[str, Optional[NormalizedRect], Optional[Any]]]]:
    """Group (text, bbox, style) fragments sharing a y0 into a visual row.

    A boxed table's columns are often separate PDF text lines that just
    happen to share a baseline ("0" and "00000000" and "32" and "00100000"
    all start at the same y0, because the columns are laid out side by
    side) — the block's own `inlines` order does not reflect that. Fragments
    with no bbox cannot be placed on a row with anything and go one-per-row.
    """
    with_bbox = [item for item in rows if item[1] is not None]
    without_bbox = [item for item in rows if item[1] is None]
    with_bbox.sort(key=lambda tb: tb[1].y0)

    grouped: List[List[Tuple[str, Optional[NormalizedRect], Optional[Any]]]] = []
    for item in with_bbox:
        if grouped and abs(item[1].y0 - grouped[-1][0][1].y0) < _ROW_Y_TOLERANCE:
            grouped[-1].append(item)
        else:
            grouped.append([item])

    grouped = _merge_stray_rows(grouped)

    for item in grouped:
        item.sort(key=lambda tb: tb[1].x0)

    grouped.extend([item] for item in without_bbox)
    return grouped


def _merge_stray_rows(
    grouped: List[List[Tuple[str, Optional[NormalizedRect], Optional[Any]]]],
) -> List[List[Tuple[str, Optional[NormalizedRect], Optional[Any]]]]:
    """Fold a row sitting far closer to its neighbor than a real row step.

    A real, decades-old typeset table can place an ellipsis dot a few points
    below the line above it - well past _ROW_Y_TOLERANCE, so it survives
    grouping as its own row, but nowhere near the table's own normal
    row-to-row spacing either (found on the Fig. 1.2 fixture: a dot at
    +4.9pt when every real row step there is ~14.7-15.2pt). That gap size is
    itself the tell: a row closer to its neighbor than roughly half the
    table's typical step is sharing that neighbor's line, not starting a
    genuine new one, and gets folded into whichever neighbor it sits closer
    to. Rows spaced at or near the typical step are never touched.
    """
    if len(grouped) < 2:
        return grouped
    y0s = [row[0][1].y0 for row in grouped]
    gaps = [y0s[i + 1] - y0s[i] for i in range(len(y0s) - 1)]
    if not gaps:
        return grouped
    if len(gaps) >= 2:
        typical_step = sorted(gaps)[len(gaps) // 2]
        threshold = typical_step * 0.6
    else:
        # Only two candidate rows: no gap-to-gap comparison is possible to
        # tell a genuine second row from baseline jitter on the same line
        # (found on the messy voltage-regulator fixture: a label
        # "Line Regulation"/"Tj - 25*C" sits 0.0048 below its own row's data
        # fragments, closer than the fragments' own 0.0061 line height, so
        # it reads as a second stacked row when it is really the same
        # printed line at a slightly different baseline). The fragments'
        # own line height is the next best proxy here: two groups still
        # within one line's height of each other are the same printed line,
        # not a real row step apart (a real row step is a full line height
        # PLUS the gap between lines, so this stays well clear of genuine
        # stacked rows).
        heights = [
            f[1].y1 - f[1].y0 for row in grouped for f in row if f[1] is not None
        ]
        typical_step = sorted(heights)[len(heights) // 2] if heights else gaps[0]
        threshold = typical_step
    if typical_step <= 0:
        return grouped

    # A row with only ONE fragment folding into a neighbor that ALREADY
    # has several of its own is a different situation than two groups
    # that are each a small piece of the SAME printed line (the
    # documented "Line Regulation"/"Tj - 25*C" case: 2 fragments merging
    # into another group). A bare, isolated single fragment sitting near
    # an already-complete data row (own label + condition + value + unit)
    # reads instead as a genuine, if tightly-spaced, NEW row - confirmed
    # directly on the same fixture: "Quiescent Current Change" (1
    # fragment, nothing else at its own y0) sits 0.0045 below "with
    # line"'s own already-4-fragment group ("with line" + its condition +
    # value + unit), a gap barely different from "Line Regulation"'s
    # documented 0.0048 - geometry alone can't tell these apart, but
    # fragment count can: "Line Regulation" only ever merges because it
    # is ITSELF paired with "Tj - 25*C" (2 fragments) before this
    # function runs, never as a lone fragment on its own line the way
    # "Quiescent Current Change" is. Merging it here silently dropped
    # "Quiescent Current Change" from the rendered table entirely
    # (overwritten by "with line" once both landed in the same grid row -
    # see src/assembler/latex_builder.py's own collision handling).
    # A bare stray dot/ellipsis ("•", the ORIGINAL case this function
    # was built for - RFC 0001 SS2.4's Fig. 1.2 fixture) is also a lone
    # fragment, and still needs to merge exactly as before: the
    # fragment-count rule above only means to distinguish "a real label
    # with substantial text of its own" from "a piece of the row it's
    # merging into" - a one-or-two-character placeholder mark is
    # neither. _looks_like_separator requires 3+ repeated characters
    # (it recognizes a drawn rule line like "───", not a single glyph),
    # so it does not fire for "•" alone - a direct length check is what
    # actually distinguishes a placeholder mark from a real word here.
    merged: List[List[Tuple[str, Optional[NormalizedRect], Optional[Any]]]] = []
    merged_y0s: List[float] = []
    for row, y0 in zip(grouped, y0s):
        is_lone_label = (
            len(row) == 1 and len(merged[-1] if merged else []) > 1
            and len(row[0][0].strip()) > 2
        )
        if merged and (y0 - merged_y0s[-1]) < threshold and not is_lone_label:
            merged[-1] = merged[-1] + row
            continue
        merged.append(row)
        merged_y0s.append(y0)
    return merged


_COLUMN_X_TOLERANCE = 0.03  # matches src/assembler/latex_builder.py's _column_bins


def _snap_row_to_columns(
    row: List["TableCell"], grid: List[List["TableCell"]],
) -> List["TableCell"]:
    """Realign a row's cells onto the table's own existing column x0s.

    A header label ("Decimal") is shorter than the digits below it and a
    left-aligned column often starts the label further left than the
    numbers it heads - close enough to read as one column by eye, but far
    enough (here: 0.07 of page width) that _column_bins in
    src/assembler/latex_builder.py clusters it as an extra column instead of
    reusing the body's. Snapping each cell's x0 to the nearest column x0
    already established by the table body keeps the header inside the same
    columns instead of manufacturing new ones.
    """
    body_x0s = sorted(
        c.visual_layout.bounding_box.x0
        for r in grid for c in r if c.visual_layout
    )
    if not body_x0s:
        return row
    bins: List[float] = []
    for x in body_x0s:
        if bins and x - bins[-1] < _COLUMN_X_TOLERANCE:
            continue
        bins.append(x)

    snapped: List[TableCell] = []
    for cell in row:
        vl = cell.visual_layout
        if vl is None or vl.bounding_box is None:
            snapped.append(cell)
            continue
        box = vl.bounding_box
        nearest = min(bins, key=lambda b: abs(b - box.x0))
        cell.visual_layout = VisualLayout(
            bounding_box=NormalizedRect(
                x0=nearest, y0=box.y0, x1=nearest + box.width, y1=box.y1,
            ),
            page_or_screen_index=vl.page_or_screen_index,
            style=vl.style,
        )
        snapped.append(cell)
    return snapped


def _header_row_for_block(block: Any) -> Optional[List["TableCell"]]:
    """The sibling directly above a detected table, read as its header row.

    A table's own column headings ("Decimal Binary Decimal Binary") are
    often a separate PDF block from the table body - the adapter has no way
    to know they belong together (RFC 0008 §5.2), so TableDetectorAnalyzer
    grabbing only the body block silently drops the header. This is
    deliberately narrow: only a block whose own lines collapse to exactly
    one visual row (via _group_into_rows) qualifies - a wrapped multi-line
    paragraph sitting just above the table (ordinary body text, not a
    heading) produces more than one row and is correctly rejected.
    """
    fragments = [item for item in _line_rows(block) if not _looks_like_separator(item[0])]
    if not fragments:
        return None
    sub_rows = _group_into_rows(fragments)
    if len(sub_rows) != 1 or len(sub_rows[0]) < 2:
        return None
    page_idx = _page_idx(block)
    row = sorted(sub_rows[0], key=lambda item: item[1].x0 if item[1] is not None else 0.0)
    return [_make_cell(t, b, s, page_idx) for t, b, s in row]


def _table_from_lines(block: Any) -> Optional[TableBlock]:
    """A TableBlock built from one block's own lines, or None.

    Same acceptance rules as the multi-block path (_find_table_runs et al.):
    at least MIN_TABLE_ROWS candidate rows, no oversized cell, and — for a
    single visual column — enough rows or long enough text to rule out a
    short list of labels. Returns None (no mutation) when the content does
    not look like a table, so a real paragraph is never touched.
    """
    fragments = [item for item in _line_rows(block) if not _looks_like_separator(item[0])]
    if len(fragments) < MIN_TABLE_ROWS:
        return None
    if any(len(t) > MAX_CELL_TEXT_LEN for t, _, _ in fragments):
        return None

    rows = _group_into_rows(fragments)
    if len(rows) < MIN_TABLE_ROWS:
        return None

    is_single_col = all(len(row) <= 1 for row in rows)
    row_texts = [" ".join(t for t, _, _ in row) for row in rows]
    avg_text_len = sum(len(t) for t in row_texts) / len(rows)
    if is_single_col and len(rows) < 5:
        return None
    if is_single_col and avg_text_len > _SINGLE_COL_PROSE_LEN:
        # A wrapped paragraph looks exactly like a single-column "table" here
        # (its own line-wrap gives every line consistent spacing, same as a
        # real one-column table would) - RFC 0001 caught this on a real page:
        # "With the 5 V supply complete, our next concern is..." is seven
        # perfectly evenly-spaced lines, no different from a spec table's
        # rows, EXCEPT that prose wraps to near-full column width while a
        # real single-column table's entries are short (bullet lists,
        # appendix TOCs). Multi-column rows aren't affected - a genuine
        # spec-table row is judged as a whole row, not by this ceiling.
        return None
    if is_single_col and avg_text_len < 15:
        return None

    page_idx = _page_idx(block)
    grid: List[List[TableCell]] = [
        [
            TableCell(
                content=[ParagraphBlock(
                    inlines=[TextLineInline(spans=[StyledTextSpan(text=t)])],
                )],
                # Cell geometry (width/height via NormalizedRect.width/.height)
                # and typography, not just the table's outer box — the row's
                # and column's own bbox and StyleDescriptor, read straight off
                # the source line (RFC 0002: TableCell is a BaseKRMNode, it
                # already has a visual_layout slot; it was just left empty).
                visual_layout=VisualLayout(
                    bounding_box=bbox,
                    page_or_screen_index=page_idx or 0,
                    style=style,
                ) if bbox is not None else None,
            )
            for t, bbox, style in row
        ]
        for row in rows
    ]

    all_boxes = [c.visual_layout.bounding_box for r in grid for c in r if c.visual_layout]
    table_bbox = (
        NormalizedRect(
            x0=min(b.x0 for b in all_boxes), y0=min(b.y0 for b in all_boxes),
            x1=max(b.x1 for b in all_boxes), y1=max(b.y1 for b in all_boxes),
        )
        if all_boxes else _bbox(block)
    )

    col_penalty = 0.15 if is_single_col else 0.0
    cls_conf = min(0.90, 0.50 + len(rows) * 0.05 - col_penalty)

    # Build span_map: track positions occupied by cells with row_span > 1 or col_span > 1
    span_map = {}
    ncols = max((len(r) for r in grid), default=0)
    for row_idx, row in enumerate(grid):
        for col_idx, cell in enumerate(row):
            row_span = getattr(cell, "row_span", 1) or 1
            col_span = getattr(cell, "col_span", 1) or 1
            # Populate span_map for all positions this cell occupies
            for r in range(row_idx, min(row_idx + row_span, len(grid))):
                for c in range(col_idx, min(col_idx + col_span, ncols)):
                    if (r, c) != (row_idx, col_idx):  # Don't map origin to itself
                        span_map[(r, c)] = (row_idx, col_idx)

    table = TableBlock(
        grid=grid,
        row_count=len(grid),
        column_count=max((len(r) for r in grid), default=0),
        parent_container_id=block.parent_container_id,
        provenance_info=block.provenance_info,
        visual_layout=VisualLayout(
            bounding_box=table_bbox or _bbox(block),
            page_or_screen_index=page_idx or 0,
        ) if table_bbox else block.visual_layout,
        extraction_confidence=block.extraction_confidence,
        classification_confidence=cls_conf,
        confidence_score=min(block.extraction_confidence, cls_conf),
        span_map=span_map,
    )
    table.id = block.id  # RFC 0001 §2.3: reclassification keeps identity
    return table


_STRAY_COLUMN_MAX_SIZE = 3
_STRAY_COLUMN_Y_MARGIN = 0.01


def _absorb_stray_columns(
    columns: List[List[Tuple[int, ParagraphBlock]]],
) -> List[List[Tuple[int, ParagraphBlock]]]:
    """Fold a tiny x-band cluster into a bigger one whose y-range covers it.

    _cluster_columns bands blocks purely by x-overlap, so a table with a
    row occasionally split across three sibling blocks - a label, a
    condition, and a value at three different x0s (found on the messy
    voltage-regulator fixture: "Output Voltage" / "5mA<l0UT<1JOA K15W" /
    "114 124 V") - can put that value fragment in its own x-band, far
    enough from the label column's x-range to never merge. Left alone, that
    tiny cluster (here: 1-2 blocks) becomes its OWN run, detected and
    inserted as a separate table stub at whatever position IT happens to
    sit at in the document's children - later concatenated onto the real
    table by _merge_adjacent_tables in child-index order, not true y-order,
    scattering that row's own value cells to wherever the stub landed
    (often the very end). A genuine second table beside this one would
    have a comparably-sized cluster, not a 1-3-block straggler, and its
    y-range would extend past the first table's - vertical containment
    inside an already-substantial cluster is what marks a cluster as a
    stray column of the SAME table rather than one of its own.
    """
    def y_range(column: List[Tuple[int, ParagraphBlock]]) -> Tuple[float, float]:
        ys = [_bbox(b).y0 for _, b in column]
        return min(ys), max(ys)

    big = [c for c in columns if len(c) > _STRAY_COLUMN_MAX_SIZE]
    small = [c for c in columns if len(c) <= _STRAY_COLUMN_MAX_SIZE]
    for stray in small:
        s_lo, s_hi = y_range(stray)
        for host in big:
            h_lo, h_hi = y_range(host)
            if h_lo - _STRAY_COLUMN_Y_MARGIN <= s_lo and s_hi <= h_hi + _STRAY_COLUMN_Y_MARGIN:
                host.extend(stray)
                break
        else:
            big.append(stray)
    return big


def _cluster_columns(
    blocks_with_idx: List[Tuple[int, ParagraphBlock]],
) -> List[List[Tuple[int, ParagraphBlock]]]:
    """Group blocks by overlapping x-ranges (column clusters)."""
    if not blocks_with_idx:
        return []

    sorted_by_x = sorted(blocks_with_idx, key=lambda t: _bbox(t[1]).x0)
    clusters: List[List[Tuple[int, ParagraphBlock]]] = [[sorted_by_x[0]]]

    for item in sorted_by_x[1:]:
        bb = _bbox(item[1])
        placed = False
        for cluster in clusters:
            representative_bb = _bbox(cluster[0][1])
            if _x_overlaps(bb, representative_bb):
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])

    return clusters
