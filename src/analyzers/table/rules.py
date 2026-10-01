"""table: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.table.signals import MAX_BLOCK_HEIGHT, MAX_CELL_TEXT_LEN, MIN_TABLE_ROWS, X_OVERLAP_THRESHOLD, Y_STEP_TOLERANCE, _SEPARATOR_RE, _SINGLE_COL_PROSE_LEN, _TAB_SPLIT_RE, log
import logging
import re
from dataclasses import dataclass
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


# A printed rule is continuous; only scan dropout breaks it. A gap wider
# than this is where the rule really stops (the voltage-regulator
# fixture's sub-row rules start 32pt into their column).
_RULE_GAP_PT = 2.0


def _rule_extent(np, ink, run: Tuple[int, int]) -> Tuple[int, int]:
    """The pixel columns a horizontal rule actually covers: the longest
    stretch its band is inked along, bridging dropout gaps."""
    # Inked on any of the rule's rows: a thin, pale rule (the DC
    # characteristics fixture's is two pixels of mid grey) reaches the ink
    # threshold on one row here and the other there, and asking for most
    # of its rows broke it into pieces.
    covered = ink[run[0]:run[1]].any(axis=0)
    max_gap = int(_RULE_GAP_PT * _RULE_ZOOM)
    best, start, last = (0, 0), None, None
    for x in np.nonzero(covered)[0]:
        if start is None or x - last > max_gap:
            start = x
        last = x
        if last + 1 - start > best[1] - best[0]:
            best = (start, last + 1)
    return best


# Share of a pixel row's width a line of text inks: the tops and feet of a
# line of glyphs reach 3% and more, scan specks never 1%.
_TEXT_ROW_SHARE = 0.03


def _text_bands(np, ink, horizontal) -> List[Optional[List[float]]]:
    """Where the text under each horizontal rule starts and ends, in points
    below the rule's lower edge (None where no text follows it).

    Read off the ink between that rule and the next, leaving out vertical
    rules (any column inked down most of the band, a sub-column rule
    included) and the two rules' own blurred fringes: a fringe row reaches
    30% and more, and taken for text it put the text hard against the
    rule."""
    bands: List[Optional[List[float]]] = []
    for k, (_, end) in enumerate(horizontal):
        stop = horizontal[k + 1][0] if k + 1 < len(horizontal) else ink.shape[0]
        band = ink[end:stop]
        if band.shape[0] < 2:
            bands.append(None)
            continue
        text = band[:, band.mean(axis=0) < 0.8].mean(axis=1) >= _TEXT_ROW_SHARE
        top, bottom = 0, len(text)
        while top < bottom and text[top]:
            top += 1
        while bottom > top and text[bottom - 1]:
            bottom -= 1
        rows = np.nonzero(text[top:bottom])[0] + top
        bands.append(
            [float(rows[0]) / _RULE_ZOOM, float(rows[-1] + 1) / _RULE_ZOOM] if rows.size else None
        )
    return bands


# Share of a band's pixel rows a column must be inked on to be a rule
# through that band: a glyph's stroke never runs a whole row's height.
_SUB_RULE_COVER = 0.9
# Pixel columns apart that still belong to one rule, from band to band.
_SUB_RULE_JOIN_PX = 3


def _sub_column_rules(np, ink, horizontal, rule_cols) -> List[Tuple[float, int, int]]:
    """Vertical rules that run between two horizontal rules only, as
    (pixel column, first rule index, last rule index).

    The voltage-regulator fixture splits CONDITIONS into "Tj = 25 C" and
    its ranges for the Line and Load Regulation rows only, and parts
    "with line"/"with load" off their label for two rows: rules too short
    to count as column rules, drawn from one horizontal rule to another.
    Each band between two horizontal rules is read on its own, the table's
    full column rules left out, and a rule found in consecutive bands at
    the same place is one rule."""
    found: List[Tuple[float, int, int]] = []
    for k in range(len(horizontal) - 1):
        band = ink[horizontal[k][1]:horizontal[k + 1][0]]
        if band.shape[0] < 3:
            continue
        lines = (band.mean(axis=0) >= _SUB_RULE_COVER) & ~rule_cols
        xs = np.nonzero(lines)[0]
        groups: List[List[int]] = []
        for x in xs:
            if groups and x - groups[-1][-1] <= 1:
                groups[-1].append(int(x))
            else:
                groups.append([int(x)])
        for g in groups:
            centre = (g[0] + g[-1]) / 2.0
            for i, (x, first, last) in enumerate(found):
                if last == k and abs(x - centre) <= _SUB_RULE_JOIN_PX:
                    found[i] = (x, first, k + 1)
                    break
            else:
                found.append((centre, k, k + 1))
    return found


def _frame_rules(np, pymupdf, page, bbox):
    """The rules that can frame a table, read down the whole page height
    within its columns.

    Returns (rules, ruled_between): every horizontal rule across most of
    the table's width as (y, x0, x1) page fractions, and a test for whether
    a band of the page between two y's is crossed top to bottom by a
    vertical rule - a cell of a ruled grid, whatever its text."""
    # The whole page is rendered so a rule is measured for its full length,
    # past the part of the table detection found; a row is a rule when it
    # is inked across most of that part's width.
    page_w, page_h = page.rect.width, page.rect.height
    clip = page.rect
    pix = page.get_pixmap(matrix=pymupdf.Matrix(_RULE_ZOOM, _RULE_ZOOM), clip=clip)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < _RULE_INK_LEVEL
    lo_px = int(bbox.x0 * page_w * _RULE_ZOOM)
    hi_px = int(bbox.x1 * page_w * _RULE_ZOOM)
    horizontal = _rule_runs(ink[:, lo_px:hi_px].sum(axis=1) > _RULE_SPAN * max(1, hi_px - lo_px))
    rules = []
    for run in horizontal:
        a, b = _rule_extent(np, ink, run)
        rules.append((
            (clip.y0 + (run[0] + run[1]) / 2.0 / _RULE_ZOOM) / page_h,
            (clip.x0 + a / _RULE_ZOOM) / page_w,
            (clip.x0 + b / _RULE_ZOOM) / page_w,
        ))
    rule_rows = np.zeros(ink.shape[0], dtype=bool)
    for a, b in horizontal:
        rule_rows[max(0, a - 2):b + 2] = True

    def ruled_between(lo: float, hi: float) -> bool:
        top = int((lo * page_h - clip.y0) * _RULE_ZOOM)
        bottom = int((hi * page_h - clip.y0) * _RULE_ZOOM)
        band = ink[max(0, top):max(0, bottom)][~rule_rows[max(0, top):max(0, bottom)]]
        return band.shape[0] >= 3 and bool((band.mean(axis=0) >= _SUB_RULE_COVER).any())

    return rules, ruled_between


def _render_table_ink(np, pymupdf, page, bbox):
    """The table's region as an ink mask, with its rules found.

    Returns (ink, clip, horizontal, vertical), or None when the region is
    too small to render: ink is a boolean array at _RULE_ZOOM over clip
    (the table's box plus _RULE_PAD_PT), horizontal/vertical are the
    pixel runs of the rules.
    """
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

    # "Most of the table" means most of the TABLE, not of the padded crop.
    # Measured against the crop, a rule spanning exactly the table covers
    # W / (W + 2 * _RULE_PAD_PT) of it, which falls under _RULE_SPAN for
    # any table shorter or narrower than ~60pt: a three-row table 40pt tall
    # lost every column rule (40 / 80 = 50%).
    table_w_px = max(1.0, (min(bbox.x1 * page_w, clip.x1) - max(bbox.x0 * page_w, clip.x0)) * _RULE_ZOOM)
    table_h_px = max(1.0, (min(bbox.y1 * page_h, clip.y1) - max(bbox.y0 * page_h, clip.y0)) * _RULE_ZOOM)
    horizontal = _rule_runs(ink.sum(axis=1) > _RULE_SPAN * table_w_px)
    vertical = _rule_runs(ink.sum(axis=0) > _RULE_SPAN * table_h_px)
    return ink, clip, horizontal, vertical


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
    rendered = _render_table_ink(np, pymupdf, page, bbox)
    if rendered is None:
        return None
    ink, clip, horizontal, vertical = rendered
    height, width = ink.shape
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
    # Where each horizontal rule starts and ends. Not every rule crosses
    # the whole table: the voltage-regulator fixture rules its sub-rows
    # ("14.5 V < VIN < 30 V" over "16 V < VIN < 22 V") only from their own
    # sub-column on, and leaves the label beside them unruled.
    rule_x_extent = [
        [(clip.x0 + px / _RULE_ZOOM) / page_w for px in _rule_extent(np, ink, run)]
        for run in horizontal
    ]

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

    # The same thing one axis over. A table's real height is the span
    # between the rules it was drawn with, and bbox - the union of the
    # CELLS' boxes - stops at the outermost glyph instead, missing the
    # rules themselves and the air the source left above the first row
    # and below the last. Measured rule-to-rule, the decimal/binary
    # fixture is 364.9pt tall while its bbox says 350.4, and the
    # voltage-regulator one is 190.8pt against a bbox of 172.1 - so the
    # height every rebuilt table was solved for was 14-19pt short of the
    # real thing, and the difference came back out of the padding above
    # and below the rows.
    outer_top = max((y for y in rule_y if y <= bbox.y0), default=None)
    outer_bottom = min((y for y in rule_y if y >= bbox.y1), default=None)

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
    # Each vertical rule's pixel columns: its detected core, widened over
    # its blurred flanks for as long as they stay inked on a tenth of the
    # rows the core is, and one pixel more. Scan rules are neither solid
    # (the decimal/binary fixture's core covers 53-75% of the rows) nor
    # sharp (four flank pixels each side at 30-50%).
    _cover = _rows_kept.mean(axis=0) if _rows_kept.shape[0] else np.zeros(width)
    _rule_cols = np.zeros(width, dtype=bool)
    for _a, _b in vertical:
        _core = float(_cover[_a:_b].mean()) if _b > _a else 0.0
        _l, _r = _a, _b
        while _l > 0 and _cover[_l - 1] >= 0.1 * _core:
            _l -= 1
        while _r < width and _cover[_r] >= 0.1 * _core:
            _r += 1
        _rule_cols[max(0, _l - 1):min(width, _r + 1)] = True
    for _i in range(len(_bands) - 1):
        # The band runs from rule to rule; the rules' own pixels - core and
        # blurred flanks alike - are taken out by what they are (_rule_cols),
        # not by a fixed clearance: 3pt from each rule's centre also hid
        # any glyph set closer than that to its rule.
        _lo = int((_bands[_i] * page_w - clip.x0) * _RULE_ZOOM)
        _hi = int((_bands[_i + 1] * page_w - clip.x0) * _RULE_ZOOM)
        _lo = max(0, min(width - 1, _lo))
        _hi = max(0, min(width, _hi))
        if _hi <= _lo:
            ink_x0.append(None)
            ink_x1.append(None)
            continue
        # A glyph column is inked on a good share of the rows the column
        # holds text on; a scan speck on a row or two. Against an absolute
        # floor alone, specks at the floor carried the voltage-regulator
        # fixture's TYP column 2.3pt past where its figures end, to 486.6
        # where the print stops at 484.3. A tenth of the column's own
        # densest pixel column separates the two there.
        _band_rows = np.where(_rule_cols[_lo:_hi], 0, _col_ink_rows[_lo:_hi])
        _noise = _MIN_INK_ROW_SHARE * max(1, _rows_kept.shape[0])
        _cols = np.nonzero(_band_rows > max(_noise, 0.1 * float(_band_rows.max(initial=0))))[0]
        if _cols.size == 0:
            ink_x0.append(None)
            ink_x1.append(None)
            continue
        ink_x0.append((clip.x0 + (_lo + int(_cols[0])) / _RULE_ZOOM) / page_w)
        ink_x1.append((clip.x0 + (_lo + int(_cols[-1]) + 1) / _RULE_ZOOM) / page_w)

    if (
        internal_rule_x or rule_y
        or outer_left is not None or outer_right is not None
        or outer_top is not None or outer_bottom is not None
    ):
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
        # Every horizontal rule, not just the outer two: the assembler sets
        # a ruled row's height from the distance between its own rules,
        # because a row's text steps are not that distance - sub-rows and
        # wrapped cells inside one ruled band put them anywhere in it.
        if rule_y:
            md["rule_y"] = sorted(rule_y)
            md["rule_x_extent"] = [e for _, e in sorted(zip(rule_y, rule_x_extent))]
            # Each horizontal rule's own weight, in PDF points: a scan does
            # not print its rules alike (the voltage-regulator fixture's
            # run 1.0 to 1.7pt), and one median weight for all left every
            # rule a pixel row or two off its source in the overlay.
            md["rule_weight_pt"] = [
                (b - a) / _RULE_ZOOM for _, (a, b) in sorted(zip(rule_y, horizontal), key=lambda z: z[0])
            ]
            # Sub-column rules, by x and the two horizontal rules they join.
            md["sub_rule"] = [
                [(clip.x0 + (x + 0.5) / _RULE_ZOOM) / page_w, rule_y[first], rule_y[last]]
                for x, first, last in _sub_column_rules(np, ink, horizontal, _rule_cols)
            ]
            # Where the source printed the text under each rule, off the
            # ink: a cell's box comes from the text layer and says nothing
            # about where the glyphs actually sit.
            md["text_band_pt"] = [
                t for _, t in sorted(zip(rule_y, _text_bands(np, ink, horizontal)), key=lambda z: z[0])
            ]
        if outer_top is not None:
            md["table_rule_y0"] = outer_top
        if outer_bottom is not None:
            md["table_rule_y1"] = outer_bottom
        # How heavy this table's rules are printed: the median width of its
        # rule runs at the same ink threshold the rules were found with.
        # Scanned tables print theirs at 1.0-2.0pt (decimal/binary median
        # 1.67pt, voltage-regulator 1.33pt); drawing them at LaTeX's 0.4pt
        # default put most of the voltage-regulator fixture's overlay
        # mismatch (54% of it) on its nineteen rule lines alone.
        _widths = sorted((b - a) / _RULE_ZOOM for a, b in horizontal + vertical)
        if _widths:
            md["rule_width_pt"] = _widths[len(_widths) // 2]
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
        # This reach is known to be wrong and is left alone deliberately.
        # It scales with the GLYPHS while a rule sits in the gap set by
        # the LEADING, so it penalises small type: the voltage-regulator
        # fixture's header cells are 5.09pt tall and the rule above them
        # is 5.3pt away - rejected by 0.21pt - so that table draws 17
        # rules where its source draws 20, while the decimal/binary
        # fixture's 14.28pt cells accept a rule 3.7pt off with room to
        # spare.
        #
        # Using the row's own STEP instead is the right measure (a rule
        # between two rows borders both; one further than a whole step
        # belongs to neither, which is what keeps the decimal/binary
        # fixture's row 2 - nearest rule 19.4pt off against a 14.7pt
        # step - correctly unruled where any blanket multiple of the
        # cell height would invent one). Tried, and it does exactly what
        # it should to the count: 17 rules -> 20, against the source's
        # 20, with fixture A untouched.
        #
        # It is reverted because of what the new flags switch on
        # downstream: the header gaining border_top makes _has_top_rule
        # true for that table, which turns on the top vskip and the
        # rule-air split in the assembler, and the table went +0.5pt ->
        # +18.0pt rule-to-rule with its fair overlay 23.7% -> 25.1%.
        #
        # Both halves have since been measured apart, and the "+18pt"
        # turns out to be mostly an artefact of the comparison.
        #
        # The rule-air split is height-neutral by construction and the
        # emitted table proves it: ten splits totalling 23.45pt appear
        # as vskips under rules and the same amounts vanish from the
        # rows' own extras (row 6: +15.83 -> +10.50 beside a 5.33
        # vskip). With the split switched off the table is still +18pt.
        # It costs 0.44pp of that fixture's fair overlay and no height.
        #
        # The real growth is 6.5pt - the 5.33pt vskip under the new top
        # rule plus three more rules at 0.4pt. The other 11.5pt is the
        # SPAN changing what it covers: the bottom rule moves down 6.5pt
        # but the top rule moves UP 11.1pt, because there is now a rule
        # above the header and the span measures from it.
        #
        # What is actually left wrong is the header band: 16.6pt between
        # our first two rules against the source's 12.4pt, the same
        # defect fixed on fixture A by splitting the row's extra around
        # its rule. Correcting the reach is gated on that, not on the
        # phantom 11.5pt.
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
            # The same visual row at a slightly different baseline - closer
            # than a row step, but past _ROW_GROUP_TOLERANCE, so it arrives
            # as its own group. Fold it into the row it belongs to. A bare
            # `continue` left it out of the run altogether: never part of
            # the table, never tombstoned, it stayed behind as a stray
            # paragraph next to the table it belonged in.
            current_run[-1] = current_run[-1] + groups[i]
            continue

        if current_step is None:
            current_step = step
            current_run.append(groups[i])
        elif abs(step - current_step) < Y_STEP_TOLERANCE:
            current_run.append(groups[i])
        elif len(current_run) >= MIN_TABLE_ROWS:
            runs.append(current_run)
            current_run = [groups[i]]
            current_step = None
        else:
            # The run so far was too short to be a table, but its last row
            # and this one already share the new step - that pair is where
            # a table following a heading actually starts. Restarting at
            # groups[i] alone dropped the table's first row, and made a
            # three-row table after a heading undetectable.
            current_run = [groups[i - 1], groups[i]]
            current_step = step

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


@dataclass(frozen=True)
class _EstimatedRect(NormalizedRect):
    """A box shared out of a longer line by character count, not measured:
    its x can be off by several points (the decimal/binary fixture's split
    binary values by 5pt), so nothing downstream should place by it."""


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
    # Each token is placed by its own character positions in the line,
    # spaces included - in a fixed-width face every character, the gap
    # between the numbers too, takes the same width. Sharing the width by
    # the tokens' digits alone gave the gap to the first token: in
    # "63 00111111" the binary value started at 20% of the width instead
    # of 27%, far enough to bin it under the Decimal heading.
    char_w = (bbox.x1 - bbox.x0) / max(1, len(text))
    parts: List[Tuple[str, Optional[NormalizedRect], Optional[Any]]] = []
    for match in re.finditer(r"\S+", text):
        parts.append((
            match.group(),
            _EstimatedRect(
                x0=bbox.x0 + match.start() * char_w, y0=bbox.y0,
                x1=bbox.x0 + match.end() * char_w, y1=bbox.y1,
            ),
            style,
        ))
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
    if isinstance(bbox, _EstimatedRect):
        cell.metadata["x_estimated"] = True
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


def _join_fragments(
    a: Tuple[str, Optional[NormalizedRect], Optional[Any]],
    b: Tuple[str, Optional[NormalizedRect], Optional[Any]],
) -> Tuple[str, Optional[NormalizedRect], Optional[Any]]:
    """One (text, bbox, style) fragment from two that share a cell, in x order."""
    first, second = sorted((a, b), key=lambda f: f[1].x0 if f[1] is not None else 0.0)
    box_a, box_b = first[1], second[1]
    if box_a is not None and box_b is not None:
        box = NormalizedRect(
            x0=min(box_a.x0, box_b.x0), y0=min(box_a.y0, box_b.y0),
            x1=max(box_a.x1, box_b.x1), y1=max(box_a.y1, box_b.y1),
        )
    else:
        box = box_a or box_b
    return (f"{first[0]} {second[0]}", box, first[2] or second[2])


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
            for fragment in sub_row:
                bbox = fragment[1]
                col = _nearest_bin(bbox.x0, bins) if bbox is not None else 0
                slot = by_col.setdefault(col, {})
                # Two fragments of one sub-row can land in the same bin (x0s
                # within the bin tolerance). Plain assignment kept only the
                # last one and dropped the other's text without a trace.
                slot[sr_idx] = (
                    _join_fragments(slot[sr_idx], fragment) if sr_idx in slot else fragment
                )

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
    #
    # A row within the threshold of BOTH neighbours joins the nearer one
    # (the previous on a tie). Folding always into the previous row put a
    # mark printed just above its own row onto the row before it.
    merged: List[List[Tuple[str, Optional[NormalizedRect], Optional[Any]]]] = []
    merged_y0s: List[float] = []
    carry: List[Tuple[str, Optional[NormalizedRect], Optional[Any]]] = []
    for k, (own, y0) in enumerate(zip(grouped, y0s)):
        row = carry + own
        carry = []

        def is_lone_label(other: List[Any]) -> bool:
            return len(row) == 1 and len(other) > 1 and len(row[0][0].strip()) > 2

        prev_gap = (y0 - merged_y0s[-1]) if merged else None
        next_gap = (y0s[k + 1] - y0) if k + 1 < len(y0s) else None
        to_prev = (
            prev_gap is not None and prev_gap < threshold and not is_lone_label(merged[-1])
        )
        # Only a smaller row moves forward into a fuller one: two rows within
        # the threshold of each other are a stray and its real row, and it is
        # the stray that joins. Without this a full data row printed just
        # above a lone mark was pulled forward into the mark.
        to_next = (
            next_gap is not None and next_gap < threshold
            and len(own) < len(grouped[k + 1])
            and not is_lone_label(grouped[k + 1])
        )
        if to_prev and to_next:
            to_prev, to_next = (prev_gap <= next_gap), (next_gap < prev_gap)
        if to_prev:
            merged[-1] = merged[-1] + row
        elif to_next:
            carry = row
        else:
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
        # Where the cell was actually printed, kept before the box is moved:
        # the snap puts it in the right COLUMN, but the assembler still has
        # to draw it where the source did - a "Binary" heading centred
        # over its column otherwise lands flush with the digits under it.
        cell.metadata["printed_x"] = [box.x0, box.x1]
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
    # Cell geometry and typography, not just the table's outer box - each
    # cell's own bbox and StyleDescriptor, read straight off the source
    # line (RFC 0002: TableCell is a BaseKRMNode with a visual_layout slot).
    grid: List[List[TableCell]] = [
        [_make_cell(t, bbox, style, page_idx, source_block_id=getattr(block, "id", None))
         for t, bbox, style in row]
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

    span_map = _build_span_map(grid)

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


def _build_span_map(grid: List[List["TableCell"]]) -> Dict[Tuple[int, int], Tuple[int, int]]:
    """Every (row, col) covered by a spanning cell, mapped to that cell's origin."""
    span_map: Dict[Tuple[int, int], Tuple[int, int]] = {}
    ncols = max((len(r) for r in grid), default=0)
    for row_idx, row in enumerate(grid):
        for col_idx, cell in enumerate(row):
            row_span = getattr(cell, "row_span", 1) or 1
            col_span = getattr(cell, "col_span", 1) or 1
            for r in range(row_idx, min(row_idx + row_span, len(grid))):
                for c in range(col_idx, min(col_idx + col_span, ncols)):
                    if (r, c) != (row_idx, col_idx):
                        span_map[(r, c)] = (row_idx, col_idx)
    return span_map


def _cell_x0(cell: "TableCell") -> float:
    vl = getattr(cell, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    return bb.x0 if bb is not None else 0.0


def _column_bins(grid: List[List["TableCell"]]) -> List[float]:
    """Column positions: the x0s of the fullest row, which has a cell in
    every column - the same anchoring the assembler uses to bin cells."""
    if not grid:
        return []
    return sorted(_cell_x0(c) for c in max(grid, key=len))


def _column_of(cell: "TableCell", bins: List[float]) -> int:
    x0 = _cell_x0(cell)
    return min(range(len(bins)), key=lambda k: abs(bins[k] - x0))


# A placeholder mark ("•" standing in an empty cell) is a small, round,
# solid blob. Sized against the table's own text height, so the test
# carries across type sizes: on the decimal/binary fixture its dots are
# 3.3-3.7pt against 14.3pt cells (0.23-0.26), while the ink the test must
# reject is either taller (header glyph fragments the OCR box clipped,
# 0.44-0.66, fill 0.4-0.7) or thin (rule slivers and the voltage-
# regulator fixture's condition bars, aspect ~0.2).
_MARK_SIZE_MIN = 0.15
_MARK_SIZE_MAX = 0.40
_MARK_ASPECT_MIN = 0.7
_MARK_ASPECT_MAX = 1.4
_MARK_FILL_MIN = 0.6
_MARK_CELL_MARGIN_PT = 1.5  # swallows glyph overhang the OCR box clips


# How far past a column rule a word's centre must lie to count as the
# other column's: a word straddling the rule is left where it is.
_RULE_SIDE_MARGIN_PT = 2.0


# What OCR makes of a vertical rule it reads as a character.
_RULE_GLYPHS = set("|[]!lI1")


def _split_cells_at_rules(page, table) -> None:
    """Split a cell whose words stand in more than one column.

    The text layer can run cells together across the rules between them:
    on the voltage-regulator fixture "Average Temperature Coefficient of
    Output Voltage" and "IOUT = 5 mA" came as one line; on the pin
    description fixture every row's "O | ADDRESS BUS: ..." did, its rule
    read as a "|", and each paragraph was set in the narrow Type column. The
    rules are the grid, so each word goes to the column its centre is in,
    line by line, placed by its own box on the page; a rule read as a
    character is dropped. Only a cell whose words are exactly its text is
    touched.
    """
    md = getattr(table, "metadata", None) or {}
    rules = md.get("column_rule_x") or []
    if not rules:
        return
    pw, ph = page.rect.width, page.rect.height
    xs = [r * pw for r in rules]
    words = page.get_text("words")

    def column(w) -> int:
        centre = (w[0] + w[2]) / 2
        return sum(1 for x in xs if centre > x)

    def on_rule(w) -> bool:
        return w[4] in _RULE_GLYPHS and any(w[0] - 1 <= x <= w[2] + 1 for x in xs)

    def rect(ws):
        return NormalizedRect(
            x0=min(w[0] for w in ws) / pw, y0=min(w[1] for w in ws) / ph,
            x1=max(w[2] for w in ws) / pw, y1=max(w[3] for w in ws) / ph,
        )

    for row in table.grid:
        for cell in list(row):
            box = cell.visual_layout.bounding_box if cell.visual_layout else None
            if box is None:
                continue
            inside = [
                w for w in words
                if box.x0 * pw - 1 <= (w[0] + w[2]) / 2 <= box.x1 * pw + 1
                and box.y0 * ph - 1 <= (w[1] + w[3]) / 2 <= box.y1 * ph + 1
            ]
            if not inside or " ".join(w[4] for w in inside) != " ".join(_cell_text_of(cell).split()):
                continue
            kept = [w for w in inside if not on_rule(w)]
            by_column: Dict[int, List[Any]] = {}
            for w in kept:
                by_column.setdefault(column(w), []).append(w)
            if len(by_column) < 2 and len(kept) == len(inside):
                continue
            style = cell.visual_layout.style
            page_index = cell.visual_layout.page_or_screen_index
            parts = []
            for col in sorted(by_column):
                ws = by_column[col]
                lines: Dict[Tuple[int, int], List[Any]] = {}
                for w in ws:
                    lines.setdefault((w[5], w[6]), []).append(w)
                text = "\n".join(
                    " ".join(w[4] for w in sorted(line, key=lambda w: w[7]))
                    for line in sorted(lines.values(), key=lambda l: min(w[1] for w in l))
                )
                parts.append((text, rect(ws)))
            first, rest = parts[0], parts[1:]
            cell.content = [ParagraphBlock(
                inlines=[TextLineInline(spans=[StyledTextSpan(text=first[0])])],
            )]
            cell.visual_layout = VisualLayout(
                bounding_box=first[1], page_or_screen_index=page_index, style=style,
            )
            for text, r in rest:
                row.append(_make_cell(text, r, style, page_index))
            row.sort(key=_cell_x0)
    table.span_map = _build_span_map(table.grid)


# How much heavier than the table's usual word a word's strokes must be
# to have been printed bold.
_BOLD_STROKE_RATIO = 1.3
_STROKE_ZOOM = 6.0


def _bold_words(page, words: List[Any]) -> Dict[int, bool]:
    """Which words, by index into `words`, were printed bold.

    Each word's stroke is read off the page at _STROKE_ZOOM: the median
    length of its runs of ink along pixel rows, a stem's width for most of
    them. A word is bold when its strokes are clearly heavier than the
    median word's in the same table - measured against the table itself,
    since a scan's absolute stroke widths depend on its resolution and
    blur, while a key phrase set bold in a regular paragraph (the pin
    description fixture's "ADDRESS BUS:") stands out against its own
    neighbours."""
    try:
        import numpy as np
        import pymupdf
    except ImportError:
        return {}
    if not words:
        return {}
    region = pymupdf.Rect(
        min(w[0] for w in words), min(w[1] for w in words),
        max(w[2] for w in words), max(w[3] for w in words),
    )
    pix = page.get_pixmap(matrix=pymupdf.Matrix(_STROKE_ZOOM, _STROKE_ZOOM), clip=region)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < _RULE_INK_LEVEL
    strokes: Dict[int, float] = {}
    for k, w in enumerate(words):
        x0 = int((w[0] - region.x0) * _STROKE_ZOOM)
        x1 = int((w[2] - region.x0) * _STROKE_ZOOM)
        y0 = int((w[1] - region.y0) * _STROKE_ZOOM)
        y1 = int((w[3] - region.y0) * _STROKE_ZOOM)
        patch = ink[max(0, y0):y1, max(0, x0):x1]
        if patch.size == 0:
            continue
        runs = []
        for row in patch:
            edges = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
            runs.extend(edges[1::2] - edges[::2])
        if runs:
            strokes[k] = float(np.median(runs)) / _STROKE_ZOOM
    if not strokes:
        return {}
    usual = sorted(strokes.values())[len(strokes) // 2]
    return {k: v > _BOLD_STROKE_RATIO * usual for k, v in strokes.items()}


def _smoothed(flags: List[bool]) -> List[bool]:
    """A line's bold flags with each lone word between two neighbours
    that agree taking their weight: a word's stroke is measured on a few
    letters and is noisy, while a bold phrase runs on - the pin description
    fixture read "LATCH" in "ADDRESS LATCH ENABLE:" as regular and a lone
    "set" in a regular paragraph as bold."""
    out = list(flags)
    # left to right, against the corrected word before: judged against the
    # raw one, "ENABLE:" saw a regular "LATCH" beside it and turned regular
    for k in range(1, len(flags) - 1):
        if out[k - 1] == flags[k + 1] != flags[k]:
            out[k] = out[k - 1]
    return out


def _runs(line: List[Any]) -> List[List[Any]]:
    """A printed line's words in runs, split where the gap between two
    words is wider than the words are tall - a column of a nested table.
    A justified paragraph stretches its word spaces to half that and more,
    and split there its words ran into each other in our wider face."""
    runs: List[List[Any]] = [[line[0]]]
    for prev, w in zip(line, line[1:]):
        if w[0] - prev[2] > (w[3] - w[1]):
            runs.append([w])
        else:
            runs[-1].append(w)
    return runs


def _regrid_ruled_bands(page, table) -> None:
    """Rebuild the rows of a ruled grid from its rules and the page's words.

    In a table ruled both ways a row is the band between two horizontal
    rules and a cell the rectangle between two rules each way; the text
    layer's own grouping does not know that - tesseract runs a paragraph's
    lines into one block across the rule under it, and the rows built from
    those blocks carried one cell's lines into the next row (the pin
    description fixture's "or peripheral is ready..." into HOLD's). So a
    band whose lines after the first stay in one column - a paragraph and
    its continuations, a nested list - becomes one row, each column's cell
    the words inside it, line by line. A band whose lines fill several
    columns is real rows of its own (the decimal/binary fixture's body,
    ruled only above and below) and is left as it is.
    """
    md = getattr(table, "metadata", None) or {}
    rule_x = md.get("column_rule_x") or []
    rule_y = md.get("rule_y") or []
    if not rule_x or len(rule_y) < 2:
        return
    pw, ph = page.rect.width, page.rect.height
    xs = [x * pw for x in rule_x]
    bb = table.visual_layout.bounding_box

    def column(w) -> int:
        return sum(1 for x in xs if (w[0] + w[2]) / 2 > x)

    words = [
        w for w in page.get_text("words")
        if bb.x0 * pw - 2 <= (w[0] + w[2]) / 2 <= bb.x1 * pw + 2
        and not (w[4] in _RULE_GLYPHS and any(w[0] - 1 <= x <= w[2] + 1 for x in xs))
    ]
    bold = _bold_words(page, words)
    is_bold = {id(w): bold.get(k, False) for k, w in enumerate(words)}
    cells = [c for row in table.grid for c in row if c.visual_layout and c.visual_layout.bounding_box]

    def style_at(r: NormalizedRect):
        def overlap(c):
            b = c.visual_layout.bounding_box
            return max(0.0, min(b.x1, r.x1) - max(b.x0, r.x0)) * max(0.0, min(b.y1, r.y1) - max(b.y0, r.y0))
        best = max(cells, key=overlap, default=None)
        return best.visual_layout.style if best is not None and overlap(best) > 0 else None

    def centre_y(cell) -> float:
        b = cell.visual_layout.bounding_box
        return (b.y0 + b.y1) / 2

    new_grid: List[List["TableCell"]] = []
    changed = False
    bands = list(zip(rule_y, rule_y[1:]))
    for lo, hi in bands:
        in_band = sorted(
            (w for w in words if lo * ph < (w[1] + w[3]) / 2 < hi * ph),
            key=lambda w: (w[1] + w[3]) / 2,
        )
        # Printed lines, by where the words sit, not by tesseract's own
        # block and line numbers: it reads a nested table's columns as
        # blocks of their own ("IO/M", "S1", "S0", "Status" on one line came
        # as four), and a paragraph's last words as a line apart.
        printed: List[List[Any]] = []
        for w in in_band:
            centre = (w[1] + w[3]) / 2
            if printed and abs(centre - sum((v[1] + v[3]) / 2 for v in printed[-1]) / len(printed[-1])) \
                    < 0.5 * (w[3] - w[1]):
                printed[-1].append(w)
            else:
                printed.append([w])
        rows_y: List[List[Tuple[int, List[Any]]]] = []
        for line in printed:
            by_col: Dict[int, List[Any]] = {}
            for w in line:
                by_col.setdefault(column(w), []).append(w)
            rows_y.append(sorted(by_col.items()))
        old_rows = [row for row in table.grid if row and lo < centre_y(row[0]) < hi]
        one_row = len(rows_y) > 1 and all(len({col for col, _ in r}) == 1 for r in rows_y[1:])
        if not one_row:
            new_grid.extend(old_rows)
            continue
        changed = True
        per_column: Dict[int, List[List[Any]]] = {}
        for r in rows_y:
            for col, ws in r:
                per_column.setdefault(col, []).append(sorted(ws, key=lambda w: w[0]))
        row: List["TableCell"] = []
        for col in sorted(per_column):
            ws_lines = per_column[col]
            flat = [w for line in ws_lines for w in line]
            r = NormalizedRect(
                x0=min(w[0] for w in flat) / pw, y0=min(w[1] for w in flat) / ph,
                x1=max(w[2] for w in flat) / pw, y1=max(w[3] for w in flat) / ph,
            )
            text = "\n".join(" ".join(w[4] for w in line) for line in ws_lines)
            part = _make_cell(text, r, style_at(r), table.visual_layout.page_or_screen_index)
            # Where each run of words on a line was printed - a nested
            # table's columns, an indented sub-item - so the builder can set
            # it there: runs split where the gap is wider than a line is tall.
            part.metadata["line_segments"] = [
                [[seg[0][0] / pw, " ".join(w[4] for w in seg)] for seg in _runs(line)]
                for line in ws_lines
            ]
            # and which of its words were printed bold, word by word
            part.metadata["line_bold"] = [_smoothed([is_bold[id(w)] for w in line]) for line in ws_lines]
            row.append(part)
        new_grid.append(row)
    if not changed:
        return
    # rows outside every band (above the first rule, below the last) stay
    first, last = rule_y[0], rule_y[-1]
    above = [row for row in table.grid if row and centre_y(row[0]) <= first]
    below = [row for row in table.grid if row and centre_y(row[0]) >= last]
    table.grid = above + new_grid + below
    # In a grid the rules say which rows a cell covers, and every cell here
    # is one band's; a span inferred before (a heading over the empty cells
    # of the next line) would now reach over a real row and hide it.
    for row in table.grid:
        for cell in row:
            cell.row_span = 1
    table.row_count = len(table.grid)
    table.column_count = max((len(r) for r in table.grid), default=0)
    table.span_map = _build_span_map(table.grid)


def _fold_label_rows(table) -> None:
    """Fold a row holding nothing but a label beside a block of sub-rows
    into the sub-row above it, once the rules are known.

    The voltage-regulator fixture prints "Quiescent Current Change" once,
    centred on the rule between its "with line" and "with load" sub-rows,
    and grouping by y gives it a row of its own between them. A row is
    folded only when it is one real label (not a mark), no measured rule
    separates it from the row above, and it shares no x with the rows on
    either side - so it prints beside them, not under their content. The
    builder then sets it beside "with line" and lowers it to where it
    was printed.
    """
    md = getattr(table, "metadata", None) or {}
    rules = md.get("rule_y") or []
    grid = table.grid
    spanned = {r for r, _ in (getattr(table, "span_map", None) or {})}

    def boxes(row):
        return [c.visual_layout.bounding_box for c in row
                if c.visual_layout is not None and c.visual_layout.bounding_box is not None]

    def centre(row):
        bs = boxes(row)
        return sum((b.y0 + b.y1) / 2.0 for b in bs) / len(bs) if bs else None

    def beside(box, row):
        return all(not _x_overlaps(box, b) for b in boxes(row))

    kept: List[List["TableCell"]] = []
    new_index: Dict[int, int] = {}
    for i, row in enumerate(grid):
        label = row[0] if len(row) == 1 else None
        box = boxes([label])[0] if label is not None and boxes([label]) else None
        above = centre(kept[-1]) if kept else None
        here = centre(row)
        if (
            box is not None and above is not None and i + 1 < len(grid) and i not in spanned
            and len(_cell_text_of(label).strip()) > 2
            and not any(above < r < here for r in rules)
            and beside(box, kept[-1]) and beside(box, grid[i + 1])
        ):
            kept[-1] = sorted(kept[-1] + row, key=_cell_x0)
        else:
            kept.append(row)
        new_index[i] = len(kept) - 1
    if len(kept) == len(grid):
        return
    table.grid = kept
    table.row_count = len(kept)
    table.span_map = _build_span_map(kept)
    for mark in md.get("placeholder_marks", []):
        mark["row"] = new_index.get(mark["row"], mark["row"])


def _cell_text_of(cell: "TableCell") -> str:
    return " ".join(
        span.text for block in cell.content for inline in getattr(block, "inlines", [])
        for span in getattr(inline, "spans", []) if hasattr(span, "text")
    )


def _ink_blobs(np, mask) -> List[List[Tuple[int, int]]]:
    """8-connected blobs of a boolean mask, as lists of (y, x) pixels."""
    seen = np.zeros_like(mask, dtype=bool)
    h, w = mask.shape
    out: List[List[Tuple[int, int]]] = []
    for y, x in np.argwhere(mask):
        if seen[y, x]:
            continue
        seen[y, x] = True
        stack = [(int(y), int(x))]
        pixels: List[Tuple[int, int]] = []
        while stack:
            cy, cx = stack.pop()
            pixels.append((cy, cx))
            for ny in (cy - 1, cy, cy + 1):
                for nx in (cx - 1, cx, cx + 1):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        out.append(pixels)
    return out


# A leader's dots are small against its line; a letter or figure is not.
_LEADER_DOT_SHARE = 0.35
_LEADER_MIN_DOTS = 3
_LEADER_ZOOM = 4.0


def _dots(np, pymupdf, page, rect, line_h: float) -> Optional[int]:
    """How many dots of ink a rect holds, or None when any blob in it is
    bigger than a dot - more than _LEADER_DOT_SHARE of the line high or
    wide: a letter, a figure."""
    clip = rect & page.rect
    if clip.is_empty:
        return 0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(_LEADER_ZOOM, _LEADER_ZOOM), clip=clip)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < _RULE_INK_LEVEL
    limit = _LEADER_DOT_SHARE * line_h * _LEADER_ZOOM
    count = 0
    for blob in _ink_blobs(np, ink):
        if len(blob) < 2:
            continue
        ys = [y for y, _ in blob]
        xs = [x for _, x in blob]
        if max(ys) - min(ys) + 1 > limit or max(xs) - min(xs) + 1 > limit:
            return None
        count += 1
    return count


# How far a background may sit from white and still be paper, not a fill.
_PAPER_LEVEL = 235


def _mark_fill(np, pymupdf, page, table) -> Optional[Tuple[int, int, int]]:
    """Record the colour a table is printed on (metadata["fill_rgb"]), the
    median of its region's pixels that are not ink - when that is a colour
    and not paper. The index fixture is printed on orange."""
    bbox = table.visual_layout.bounding_box
    pw, ph = page.rect.width, page.rect.height
    clip = pymupdf.Rect(bbox.x0 * pw, bbox.y0 * ph, bbox.x1 * pw, bbox.y1 * ph) & page.rect
    if clip.is_empty:
        return None
    pix = page.get_pixmap(clip=clip)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    paper = arr[arr.mean(axis=2) >= _RULE_INK_LEVEL]
    if paper.size == 0:
        return None
    rgb = tuple(int(v) for v in np.median(paper, axis=0))
    if min(rgb) >= _PAPER_LEVEL:
        return None
    md = getattr(table, "metadata", None)
    if md is None:
        md = {}
        table.metadata = md
    md["fill_rgb"] = list(rgb)
    return rgb


def _drop_leaders(np, pymupdf, page, table) -> int:
    """Take the dot leaders out of a table's cells.

    OCR reads a leader's dots as text - on the index fixture "..... 2...
    0-0 e", "cece", "eee", lone "." - as cells of their own or run into the
    page number after them. What a leader is shows in the pixels whatever
    OCR made of it: each word of a cell is looked at, and a word that holds
    only dots of ink is a leader's - where the row has three dots of it or
    more, or is already known to carry a leader (_find_placeholder_marks
    saw one), so a lone placeholder mark between figures is not one. A cell
    left with no words goes; one left with some keeps those, on their own
    boxes. The cell before the leader is marked (metadata["leader_after"])
    so the builder can run the leader on from it. Returns how many cells
    lost words."""
    pw, ph = page.rect.width, page.rect.height
    words = page.get_text("words")
    changed = 0
    for row in table.grid:
        cells = sorted(row, key=_cell_x0)
        found = []
        for cell in cells:
            box = cell.visual_layout.bounding_box if cell.visual_layout else None
            if box is None:
                found.append(None)
                continue
            inside = [
                w for w in words
                if box.x0 * pw - 1 <= (w[0] + w[2]) / 2 <= box.x1 * pw + 1
                and box.y0 * ph - 1 <= (w[1] + w[3]) / 2 <= box.y1 * ph + 1
            ]
            line_h = (box.y1 - box.y0) * ph
            found.append([(w, _dots(np, pymupdf, page, pymupdf.Rect(w[:4]), line_h)) for w in inside])
        # The row's last word is what the leader leads to - its page number
        # - and is kept whatever its box holds: OCR's boxes drift, and on
        # that fixture the page number "7" was boxed over two leader dots.
        last = max(
            ((w, n) for ws in found if ws for w, n in ws), key=lambda wn: wn[0][2], default=None
        )
        if last is not None:
            found = [[(w, None if w is last[0] else n) for w, n in ws] if ws else ws for ws in found]
        known = any((c.metadata or {}).get("leader_after") for c in cells)
        if not known and sum(n or 0 for ws in found if ws for _, n in ws) < _LEADER_MIN_DOTS:
            continue
        keep: List["TableCell"] = []
        for cell, ws in zip(cells, found):
            leader = [w for w, n in (ws or []) if n is not None]
            if not leader or not keep:
                keep.append(cell)
                continue
            rest = [w for w, n in ws if n is None]
            keep[-1].metadata["leader_after"] = True
            changed += 1
            if not rest:
                continue
            cell.content = [ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(
                text=" ".join(w[4] for w in rest))])])]
            cell.visual_layout = VisualLayout(
                bounding_box=NormalizedRect(
                    x0=min(w[0] for w in rest) / pw, y0=min(w[1] for w in rest) / ph,
                    x1=max(w[2] for w in rest) / pw, y1=max(w[3] for w in rest) / ph,
                ),
                page_or_screen_index=cell.visual_layout.page_or_screen_index,
                style=cell.visual_layout.style,
            )
            keep.append(cell)
        row[:] = keep
    if changed:
        table.column_count = max((len(r) for r in table.grid), default=0)
        table.span_map = _build_span_map(table.grid)
    return changed


def _find_placeholder_marks(np, pymupdf, page, table) -> int:
    """Find the "•" placeholder marks the OCR layer missed, in the pixels.

    A scan's text layer does not reliably recognise a lone dot: the
    decimal/binary fixture prints eleven placeholder dots and its OCR
    layer holds five - every one of which is already a cell. The other
    six exist only as ink, and the rendered table was missing them.

    A dot is looked for in the ink that is left once every cell's box (a
    little enlarged) and every rule are cleared away, and it is only
    accepted for a cell that is EMPTY - the row it centres on has nothing
    in its column - since a placeholder is exactly what stands in for a
    missing value.

    The finds go to table.metadata["placeholder_marks"] as
    {"row", "bbox"}, NOT into the grid. The grid is the table's TEXT, as
    the source's text layer carries it (tests/e2e/test_krm_roundtrip.py
    holds it to that, cell for cell); a mark read off the pixels is a
    visual fact about the printed page, and the assembler sets it into
    its cell when it draws the table. Returns how many were found.
    """
    vl = table.visual_layout
    bbox = vl.bounding_box if vl else None
    placed = [
        c for row in table.grid for c in row
        if c.visual_layout is not None and c.visual_layout.bounding_box is not None
    ]
    if bbox is None or not placed:
        return 0
    rendered = _render_table_ink(np, pymupdf, page, bbox)
    if rendered is None:
        return 0
    ink, clip, horizontal, vertical = rendered
    ink = ink.copy()
    page_w, page_h = page.rect.width, page.rect.height
    z = _RULE_ZOOM

    def px(value: float, origin: float) -> int:
        return int(round((value - origin) * z))

    for r0, r1 in horizontal:
        ink[max(0, r0 - 2):r1 + 2, :] = False
    for c0, c1 in vertical:
        ink[:, max(0, c0 - 2):c1 + 2] = False
    m = _MARK_CELL_MARGIN_PT
    for cell in placed:
        b = cell.visual_layout.bounding_box
        ink[max(0, px(b.y0 * page_h - m, clip.y0)):px(b.y1 * page_h + m, clip.y0) + 1,
            max(0, px(b.x0 * page_w - m, clip.x0)):px(b.x1 * page_w + m, clip.x0) + 1] = False
    inside = np.zeros_like(ink)
    inside[max(0, px(bbox.y0 * page_h, clip.y0)):px(bbox.y1 * page_h, clip.y0),
           max(0, px(bbox.x0 * page_w, clip.x0)):px(bbox.x1 * page_w, clip.x0)] = True
    ink &= inside
    if not ink.any():
        return 0

    heights = sorted(c.visual_layout.bounding_box.height * page_h for c in placed)
    text_h = heights[len(heights) // 2]
    if text_h <= 0:
        return 0
    bins = _column_bins(table.grid)
    row_centres = []
    for row in table.grid:
        boxes = [c.visual_layout.bounding_box for c in row if c.visual_layout and c.visual_layout.bounding_box]
        row_centres.append(
            sum((b.y0 + b.y1) / 2.0 for b in boxes) / len(boxes) * page_h if boxes else None
        )

    marks: List[Dict[str, Any]] = []
    taken = set()
    dots_per_row: Dict[int, int] = {}
    for pixels in _ink_blobs(np, ink):
        ys = [p[0] for p in pixels]
        xs = [p[1] for p in pixels]
        w_pt = (max(xs) - min(xs) + 1) / z
        h_pt = (max(ys) - min(ys) + 1) / z
        fill = len(pixels) / ((max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1))
        if not (
            _MARK_SIZE_MIN * text_h <= w_pt <= _MARK_SIZE_MAX * text_h
            and _MARK_SIZE_MIN * text_h <= h_pt <= _MARK_SIZE_MAX * text_h
            and _MARK_ASPECT_MIN <= w_pt / h_pt <= _MARK_ASPECT_MAX
            and fill >= _MARK_FILL_MIN
        ):
            continue
        cy = clip.y0 + (sum(ys) / len(ys)) / z
        candidates = [
            (abs(c - cy), i) for i, c in enumerate(row_centres) if c is not None
        ]
        if not candidates:
            continue
        dist, row_idx = min(candidates)
        if dist > text_h / 2.0:
            continue
        dots_per_row[row_idx] = dots_per_row.get(row_idx, 0) + 1
        x0 = (clip.x0 + min(xs) / z) / page_w
        box = [
            x0, (clip.y0 + min(ys) / z) / page_h,
            (clip.x0 + (max(xs) + 1) / z) / page_w, (clip.y0 + (max(ys) + 1) / z) / page_h,
        ]
        col = min(range(len(bins)), key=lambda k: abs(bins[k] - x0)) if bins else 0
        row = table.grid[row_idx]
        if (row_idx, col) in taken or (bins and any(_column_of(c, bins) == col for c in row)):
            continue
        taken.add((row_idx, col))
        marks.append({"row": row_idx, "bbox": box})

    # A placeholder stands alone in its cell; a row of dots is a leader. On
    # the index fixture every leader's dots were taken for placeholders, a
    # "•" in each gap, and each opened a column of its own. A row with
    # _LEADER_MIN_DOTS of them or more is given its leader instead.
    leader_rows = {r for r, n in dots_per_row.items() if n >= _LEADER_MIN_DOTS}
    marks = [m for m in marks if m["row"] not in leader_rows]
    for r in leader_rows:
        row = sorted(table.grid[r], key=_cell_x0)
        if row:
            row[0].metadata["leader_after"] = True

    if marks:
        md = getattr(table, "metadata", None)
        if md is None:
            md = {}
            table.metadata = md
        md["placeholder_marks"] = marks
    return len(marks)


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
