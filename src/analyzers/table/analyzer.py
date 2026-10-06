"""table: The analyzer itself: orchestration and KRM writes."""

from typing import Any, Dict, List, Optional, Tuple
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    TableBlock,
    TableCell,
    UnknownBlock,
    VisualLayout,
)

from src.analyzers.caption.signals import _CAPTION_RE
from src.analyzers.source_io import resolve_source_path
from src.analyzers.table.boxes import _box_grid, _table_from_box_grid
from src.analyzers.table.signals import MAX_BLOCK_HEIGHT, MAX_CELL_TEXT_LEN, MIN_TABLE_ROWS, log
from src.analyzers.table.rules import _absorb_stray_columns, _bbox, _is_leader_residue, _marks_on_leaders, _reseat_stacked_lines, _build_span_map, _cell_x0, _column_bins, _column_of, _find_placeholder_marks, _frame_rules, _cluster_columns, _count_columns, _drop_leaders, _find_table_runs, _fold_label_rows, _get_text, _header_row_for_block, _looks_like_separator, _mark_cell_borders, _mark_fill, _mark_printed_width, _measure_leader_grid, _deflate_boxes, _reads_as_prose, _label_rows, _label_table, _mark_italic, _mark_typeface, _size_display_type, _mark_text_colour, _page_idx, _regrid_ruled_bands, _rows_from_block, _rows_from_group, _snap_row_to_columns, _split_cells_at_rules, _table_from_lines


def _cell_y0(cell: "TableCell") -> float:
    vl = getattr(cell, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    return bb.y0 if bb is not None else 0.0


def _cell_text(cell: "TableCell") -> str:
    return " ".join(
        s.text.strip()
        for c in cell.content
        for il in c.inlines
        for s in il.spans
    )


def _fills_empty_column(cell: "TableCell", row: List["TableCell"], bins: List[float]) -> bool:
    """True when cell's column holds nothing in row.

    Judged by column, not by box overlap: two cells can sit side by side
    without touching and still share a column, and the assembler keeps
    only one cell per column - inserting "Quiescent Current Change" beside
    "with line" (both in the label column, boxes apart) dropped it from
    the rendered table.
    """
    if not bins or getattr(cell, "visual_layout", None) is None:
        return False
    col = _column_of(cell, bins)
    return all(_column_of(other, bins) != col for other in row)


def _merge_orphan_rows(grid: List[List["TableCell"]]) -> List[List["TableCell"]]:
    """Fold a single-cell grid row into the nearest fuller row's cell.

    A multi-line CONDITIONS-style cell whose lines the source printed as
    separate PDF blocks at different y0 (e.g. "15.5V<VIN<27V" /
    "5mA<IOUT<1.0A" / "P<15W" around one "Output Voltage" data row) each
    become their own row-group in _find_table_runs, so each line arrives
    as its own sparse grid row instead of extra lines inside one cell.
    _rows_from_block's own rowspan detection never sees this - it only
    looks at sub-rows sharing ONE PDF block.

    A naive fix keyed on list position (comparing grid[row][col_idx]
    across rows) breaks here: a 1-cell row's only cell sits at list index
    0 regardless of which real column it belongs to, so it can't be
    matched against a fuller row by position. Matching by each cell's own
    x0 - the position the source actually printed it at - is what every
    other column-assignment path in this module already uses, and it is
    the only thing that identifies a column correctly when rows are
    jagged.

    Which full row an orphan belongs to is also not always "the nearest by
    row count": a condition can wrap onto a line ABOVE its data row and
    onto another BELOW it in the very same block (RFC 0001 SS2.4's
    "Output Voltage" fixture: "15.5V<VIN<27V" prints above, "P<15W" below,
    both around one data row that already absorbed the middle line via
    _rows_from_block's own rowspan). Row-count distance can't tell "one
    line above THIS row" apart from "one line above the NEXT row" - actual
    print position can. Matching each candidate row by the y0 of its own
    nearest-x0 cell (the same column the orphan would join) picks the row
    whose column entry the orphan is physically adjacent to, not just
    whichever row happens to be fewer grid rows away.
    """
    if len(grid) < 3:
        return grid

    full_indices = [i for i, row in enumerate(grid) if len(row) > 1]
    if not full_indices:
        return grid

    def _target_cell(row_idx: int, orphan_cell: "TableCell") -> "TableCell":
        return min(grid[row_idx], key=lambda c: abs(_cell_x0(c) - _cell_x0(orphan_cell)))

    # Pass 1: decide every orphan's target row using each candidate row's
    # ORIGINAL geometry, before any merge below has a chance to widen a
    # target cell's bounding_box. Deciding and applying in the same pass
    # let an EARLIER orphan's merge shift its target's bbox (see the
    # widening below) before a LATER orphan's distance to that same row
    # was measured - on the voltage-regulator fixture, merging
    # "15.5V<VIN<27V" into "Output Voltage" first pulled that row's own
    # y0 up to match it, so "P<15W" (which also belongs there, printed
    # AFTER the row) then measured closer to the NEXT row ("Quiescent
    # Current") than to its real, now-relocated target. Locking in every
    # decision from the untouched grid first removes that ordering
    # dependency entirely.
    decisions: List[Tuple[int, int, "TableCell"]] = []
    insertions: List[Tuple[int, int, Optional[int]]] = []
    bins = _column_bins(grid)
    for i, row in enumerate(grid):
        if len(row) != 1:
            continue
        orphan_cell = row[0]
        orphan_y0 = _cell_y0(orphan_cell)
        distances = {j: abs(_cell_y0(_target_cell(j, orphan_cell)) - orphan_y0) for j in full_indices}
        min_dist = min(distances.values())

        # y0 proximity alone cannot tell a TRAILING continuation line
        # (belongs to the row printed just ABOVE it) apart from a LEADING
        # one (belongs to the row printed just BELOW it) when the orphan
        # sits almost exactly between two candidate rows - confirmed on
        # the voltage-regulator fixture's "P<15W" line: 0.0088 to the row
        # below vs 0.0104 to its real row above, a tie any epsilon worth
        # having will also catch. But _rows_from_block already knows,
        # directly from the source PDF, which block each cell's text came
        # from - "P<15W" and "Output Voltage"'s own "5mA<IOUT<1.0A" cell
        # are literally two lines of the SAME PdfSourceAdapter block,
        # split apart only because nothing else printed beside "P<15W"'s
        # own line for _group_into_rows to pair it with. A shared
        # source_block_id is a direct fact about the source, not a
        # distance estimate, so it overrides any y0-based guess outright.
        orphan_block_id = orphan_cell.metadata.get("source_block_id")
        block_id_matches = [
            j for j in full_indices
            if orphan_block_id is not None
            and any(c.metadata.get("source_block_id") == orphan_block_id for c in grid[j])
        ]
        if block_id_matches:
            nearest = min(block_id_matches, key=lambda j: distances[j])
        else:
            # A full row's own "anchor" cell (nearest by x0) is not always
            # the FIRST line of its own multi-line block - _rows_from_block
            # can pick a middle line as a row-group's representative
            # (confirmed on the voltage-regulator fixture: "Output
            # Voltage"'s anchor is its SECOND condition line,
            # "5mA<IOUT<1.0A", one line further from an earlier orphan
            # than that orphan's true row - "15.5V<VIN<27V" - sits from
            # the PREVIOUS row's own last line). That makes the two real
            # candidates' distances near-equal by construction, not an
            # edge case tolerance can ignore: within one line-height of
            # each other (_TIE_EPS), prefer the LATER row, since a
            # condition line's own first line reads as the start of ITS
            # entry, not the tail of the entry printed just above it.
            _TIE_EPS = 0.006  # roughly half a line's y0-to-y0 step on this fixture
            nearest = max(j for j, d in distances.items() if d <= min_dist + _TIE_EPS)

        # Every case above assumes the orphan is a stray LINE of some
        # already-represented cell (a CONDITIONS entry wrapped across
        # blocks, a stray "*"). But a shared source_block_id also fires
        # for a genuine, standalone characteristic label that a tight
        # PDF layout printed close to - or even between - two indented
        # sub-condition labels that belong to it (RFC 0001 SS2.4's
        # voltage-regulator fixture: "Quiescent Current Change" prints
        # on its own line at the table's LABEL column x0, directly
        # below "with line" and above "with load" - both indented
        # sub-labels for the two data rows this heading covers - and
        # PdfSourceAdapter grouped all three into one block because
        # nothing else sits between them). The chosen target here is
        # "with line"'s own row, and _target_cell's nearest-x0 pick
        # lands on "with line" ITSELF (that row's own leftmost cell,
        # not some other column's value) - concatenating onto it does
        # not continue a wrapped value, it overwrites one real label
        # with two glued together ("Quiescent Current Change" + "with
        # line" as one string), which a downstream per-row height/text
        # render can't tell apart from actual wrapped content. A
        # continuation orphan (P<15W, 15.5V<VIN<27V) never targets a
        # row's own leftmost cell - it always lands on that row's
        # CONDITIONS/VALUE cell, which sits to the right of that row's
        # own label. So: when the target IS the candidate row's own
        # leftmost cell, and both sides already hold more than a
        # placeholder mark's worth of text, this orphan is not a
        # continuation - leave it standing as its own row instead of
        # folding it away.
        # An orphan standing in a column its row leaves EMPTY is that row's
        # missing cell, not a continuation of one of its cells: insert it
        # rather than fold its text into a neighbour. The voltage-regulator
        # fixture's "Average Temperature Coefficient of Output Voltage"
        # label sits in the label column between the two rows it labels,
        # overlapping none of their cells; folding was refused (its nearest
        # cell is the row's anchor), so it rendered as a row of its own.
        # Between two full rows that both lack its column, it spans them.
        if _fills_empty_column(orphan_cell, grid[nearest], bins):
            above = max((j for j in full_indices if j < i), default=None)
            below = min((j for j in full_indices if j > i), default=None)
            spans_both = (
                above is not None and below is not None
                and _fills_empty_column(orphan_cell, grid[above], bins)
                and _fills_empty_column(orphan_cell, grid[below], bins)
            )
            insertions.append((i, above if spans_both else nearest, below if spans_both else None))
            continue

        target_cell = _target_cell(nearest, orphan_cell)
        target_row_anchor = min(grid[nearest], key=_cell_x0)
        if (
            target_cell is target_row_anchor
            and len(_cell_text(target_cell).strip()) > 2
            and len(_cell_text(orphan_cell).strip()) > 2
        ):
            continue

        decisions.append((i, nearest, target_cell))

    # Pass 2: apply the merges (content + bbox widening) using pass 1's
    # decisions - now safe to mutate as we go, since nothing downstream
    # re-measures distance against a row whose bbox this loop changes.
    #
    # Order matters when several orphans join one cell from the same side.
    # Each orphan ABOVE its target is prepended, so they are applied
    # nearest-first (descending i) - applied in ascending order, lines A
    # then B above row T read "B A T". Orphans BELOW are appended, so
    # ascending order keeps them in print order. The target cell is the
    # one chosen in pass 1: re-choosing it here would measure against
    # boxes this loop has already widened.
    orphan_indices = set()
    ordered = sorted(decisions, key=lambda d: -d[0] if d[1] > d[0] else d[0])
    for i, nearest, target_cell in ordered:
        orphan_cell = grid[i][0]
        if nearest > i:
            target_cell.content = list(orphan_cell.content) + list(target_cell.content)
        else:
            target_cell.content = list(target_cell.content) + list(orphan_cell.content)

        # The merged cell now holds text that, in the source, spanned both
        # cells' own y-range - a taller cell than either alone. Widening
        # target_cell's own bounding_box to that union is what lets a
        # later per-row height calculation (RFC 0021 SS3, latex_builder's
        # row-height struts) see this row as genuinely taller instead of
        # only as tall as whichever single line target_cell started as.
        t_vl = getattr(target_cell, "visual_layout", None)
        o_vl = getattr(orphan_cell, "visual_layout", None)
        t_bb = getattr(t_vl, "bounding_box", None) if t_vl else None
        o_bb = getattr(o_vl, "bounding_box", None) if o_vl else None
        if t_vl is not None and t_bb is not None and o_bb is not None:
            t_vl.bounding_box = NormalizedRect(
                x0=min(t_bb.x0, o_bb.x0), y0=min(t_bb.y0, o_bb.y0),
                x1=max(t_bb.x1, o_bb.x1), y1=max(t_bb.y1, o_bb.y1),
            )
        orphan_indices.add(i)

    for i, target, _ in insertions:
        grid[target].append(grid[i][0])
        grid[target].sort(key=_cell_x0)
        orphan_indices.add(i)
    # A span is only right once every row between the two it covers is
    # gone - otherwise it would reach over a row that stayed.
    for i, above, below in insertions:
        if below is not None and all(k in orphan_indices for k in range(above + 1, below)):
            grid[i][0].row_span = 2

    if not orphan_indices:
        return grid
    return [row for i, row in enumerate(grid) if i not in orphan_indices]


def _on_its_own_line(cell: "TableCell", row: List["TableCell"], below: List["TableCell"]) -> bool:
    """Whether a cell sits on its own row's line, not over the rows under it.

    A label spanning rows is set between them - its box reaches into the
    next row, or its centre stands below its row-mates'. One printed level
    with its row-mates and short of the next row is that row's alone: the
    index fixture's "8,9" is APPLIED DIGITAL DATA SYSTEMS's page number,
    and was spanned over BOWERS ENGINEERING CO, whose own number OCR lost.
    A cell with no row-mates to compare with is not judged."""
    box = _bbox(cell)
    mates = [b for b in (_bbox(c) for c in row if c is not cell) if b is not None]
    under = [b for b in (_bbox(c) for c in below) if b is not None]
    if box is None or not mates or not under:
        return False
    height = box.y1 - box.y0
    centre = (box.y0 + box.y1) / 2
    mates_centre = sorted((b.y0 + b.y1) / 2 for b in mates)[len(mates) // 2]
    return abs(centre - mates_centre) < height / 4 and box.y1 <= min(b.y0 for b in under) + height / 4


def _is_box_table(node: Any) -> bool:
    """Whether a table was read off its drawn boxes (boxes._box_grid)."""
    return isinstance(node, TableBlock) and bool((node.metadata or {}).get("box_grid"))


def _infer_rowspans(grid: List[List["TableCell"]]) -> None:
    """Give a column's first cell a row_span over the rows right under it
    that have nothing in that column.

    Columns are identified by each cell's x0, binned against the fullest
    row. A grid row is ragged by list position - a row missing a MIDDLE
    column is simply shorter - so reading "index >= len(row)" as "column
    absent" treated such a row as missing its LAST column, and spanned the
    wrong cell of the row above down over a real value.
    """
    bins = _column_bins(grid)
    if not bins:
        return

    by_column: List[Dict[int, "TableCell"]] = []
    for row in grid:
        cols: Dict[int, "TableCell"] = {}
        for cell in row:
            cols.setdefault(_column_of(cell, bins), cell)
        by_column.append(cols)

    for col in range(len(bins)):
        first = next((r for r, cols in enumerate(by_column) if col in cols), None)
        if first is None or first + 1 >= len(grid) or col in by_column[first + 1]:
            continue
        if _on_its_own_line(by_column[first][col], grid[first], grid[first + 1]):
            continue
        missing = 0
        for cols in by_column[first + 1:]:
            if col in cols:
                break
            missing += 1
        by_column[first][col].row_span = missing + 1


class TableDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="TableDetectorAnalyzer",
                version="1.1.0",
                description="Detects tabular structures by spatial alignment of blocks",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
                },
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["NormalizationAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._table_count = 0
        self._detect_box_tables(doc)
        for container in doc.root_containers:
            self._detect_label_tables(container)
        for container in doc.root_containers:
            self._process_container(container)
        if self._table_count:
            log.info("TableDetectorAnalyzer: %d table(s) detected", self._table_count)
        self._absorb_framed_rows(doc)
        self._mark_borders(doc)

    def _detect_label_tables(self, container: ContainerUnit) -> None:
        """Tables of labels and values (rules._label_table) over runs of
        consecutive blocks each of whose lines is a label and its value:
        the blocks tombstoned into the table (RFC 0001 SS2.4), the table in
        the first one's place."""
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._detect_label_tables(child)
        runs: List[List[int]] = []
        for idx, child in enumerate(container.children):
            labelled = (isinstance(child, (ParagraphBlock, UnknownBlock)) and not child.is_tombstoned
                        and _bbox(child) is not None and _label_rows(child) is not None)
            if not labelled:
                if not getattr(child, "is_tombstoned", False):
                    runs.append([])
                continue
            if runs and runs[-1] and _page_idx(container.children[runs[-1][-1]]) == _page_idx(child):
                runs[-1].append(idx)
            else:
                runs.append([idx])
        for run in reversed([r for r in runs if r]):
            blocks = [container.children[i] for i in run]
            table = _label_table(blocks)
            if table is None:
                continue
            table.id = derive_composite_id("table", *[b.id for b in blocks])
            for b in blocks:
                b.is_tombstoned = True
                b.metadata = {**(b.metadata or {}), "tombstone_reason": "merged_into_table"}
            container.children.insert(run[0], table)
            self._table_count += 1

    def _detect_box_tables(self, doc: KnowledgeDocument) -> None:
        """Find the tables drawn as boxes (boxes._box_grid), before the
        text-layer detection, which cannot: a block diagram's labels line
        up with nothing. The blocks inside a box grid are tombstoned into
        it (RFC 0001 SS2.4: nothing deleted) and the table takes the first
        one's place. The passes after this one read a table's structure
        off its text and rules; a box table's is its boxes, and they leave
        it as it is (_is_box_table)."""
        path = resolve_source_path(doc)
        if not path:
            return
        try:
            import numpy as np
            import pymupdf
        except ImportError:
            return
        try:
            source = pymupdf.open(path)
        except Exception:
            return
        try:
            def walk(container: ContainerUnit) -> None:
                for child in list(container.children):
                    if isinstance(child, ContainerUnit):
                        walk(child)
                pages = sorted({
                    _page_idx(c) or 0 for c in container.children
                    if isinstance(c, (ParagraphBlock, UnknownBlock)) and not c.is_tombstoned and _bbox(c) is not None
                })
                for page_index in pages:
                    if page_index < source.page_count:
                        self._box_table_on(container, page_index, np, pymupdf, source[page_index])
            for root in doc.root_containers:
                walk(root)
        finally:
            source.close()

    def _box_table_on(self, container: ContainerUnit, page_index: int, np, pymupdf, page) -> None:
        grid = _box_grid(np, pymupdf, page)
        if grid is None:
            return
        pw, ph = page.rect.width, page.rect.height
        x0, y0, x1, y1 = grid.xs[0] / pw, grid.ys[0] / ph, grid.xs[-1] / pw, grid.ys[-1] / ph
        inside = [
            idx for idx, c in enumerate(container.children)
            if isinstance(c, (ParagraphBlock, UnknownBlock)) and not c.is_tombstoned
            and (_page_idx(c) or 0) == page_index and _bbox(c) is not None
            and x0 <= (_bbox(c).x0 + _bbox(c).x1) / 2 <= x1 and y0 <= (_bbox(c).y0 + _bbox(c).y1) / 2 <= y1
        ]
        if not inside:
            return
        blocks = [container.children[i] for i in inside]
        table = _table_from_box_grid(grid, page_index, pw, ph)
        table.id = derive_composite_id("table", *[b.id for b in blocks])
        table.parent_container_id = container.id
        table.provenance_info = blocks[0].provenance_info
        conf = sum(b.extraction_confidence for b in blocks) / len(blocks)
        table.extraction_confidence = table.confidence_score = conf
        for b in blocks:
            b.is_tombstoned = True
            b.metadata = b.metadata or {}
            b.metadata["tombstone_reason"] = "merged_into_table"
        container.children.insert(inside[0], table)
        self._table_count += 1

    def _absorb_framed_rows(self, doc: KnowledgeDocument) -> None:
        """Take into a table the rows its own frame rules enclose.

        Detection works on the page's blocks and their spacing, and stops
        where they stop looking like rows - not where the table ends. The
        DC characteristics fixture prints its header and first row above,
        and its last five rows below, a stretch the detector took; all of
        them inside the rules that frame the table. So from each edge of a
        table the region up to the next rule across its width is taken in,
        and then the region beyond that rule up to the next, for as long as
        each region is closed by a rule, holds nothing wider than that rule,
        no prose and no caption, and steps no wider than the table's own
        rows do. A heading above a table's top rule has no rule above it
        and stays where it is.
        """
        path = resolve_source_path(doc)
        if not path:
            return
        try:
            import numpy as np
            import pymupdf
        except ImportError:
            return
        try:
            source = pymupdf.open(path)
        except Exception:
            return
        try:
            def walk(container: ContainerUnit) -> None:
                for child in list(container.children):
                    if isinstance(child, ContainerUnit):
                        walk(child)
                for child in list(container.children):
                    if isinstance(child, TableBlock) and not child.is_tombstoned and not _is_box_table(child):
                        page_index = _page_idx(child) or 0
                        if child.visual_layout and page_index < source.page_count:
                            self._absorb_into(container, child, np, pymupdf, source[page_index])
            for root in doc.root_containers:
                walk(root)
        finally:
            source.close()

    def _absorb_into(self, container: ContainerUnit, table: TableBlock, np, pymupdf, page) -> None:
        bb = table.visual_layout.bounding_box
        rules, ruled_between = _frame_rules(np, pymupdf, page, bb)
        if not rules:
            return
        page_index = _page_idx(table)
        # A table read off its own drawn boxes is no row of another's: its
        # frame is its own.
        blocks = [
            c for c in container.children
            if isinstance(c, (ParagraphBlock, UnknownBlock, TableBlock)) and not c.is_tombstoned
            and c is not table and not _is_box_table(c) and _bbox(c) is not None and _page_idx(c) == page_index
        ]
        tops = sorted({_cell_y0(cell) for row in table.grid for cell in row if cell.visual_layout})
        steps = sorted(b - a for a, b in zip(tops, tops[1:]) if b - a > 0)
        max_gap = 3.0 * steps[len(steps) // 2] if steps else 0.05
        tol = 0.005

        def region(lo: float, hi: float, rule) -> Optional[List[Any]]:
            inside = [b for b in blocks if _bbox(b).y0 >= lo - tol and _bbox(b).y1 <= hi + tol]
            # A band a vertical rule crosses is a row of a ruled grid: its
            # cells may hold whole paragraphs (the pin description fixture's
            # "Name and Function" column does), and the prose and spacing
            # tests below are for telling rows from prose where no grid says.
            gridded = ruled_between(lo, hi)
            for b in inside:
                box = _bbox(b)
                if box.x0 < rule[1] - tol or box.x1 > rule[2] + tol:
                    return None
                if gridded or isinstance(b, TableBlock):
                    continue
                text = _get_text(b).strip()
                if len(text) > MAX_CELL_TEXT_LEN or _CAPTION_RE.match(text):
                    return None
            if gridded:
                return inside
            ys = sorted([lo, hi] + [y for b in inside for y in (_bbox(b).y0, _bbox(b).y1)])
            if inside and max(b - a for a, b in zip(ys, ys[1:])) > max_gap:
                return None
            return inside

        top = bb.y0
        for rule in sorted((r for r in rules if r[0] < bb.y0), key=lambda r: -r[0]):
            if region(rule[0], top, rule) is None:
                break
            top = rule[0]
        bottom = bb.y1
        for rule in sorted((r for r in rules if r[0] > bb.y1), key=lambda r: r[0]):
            if region(bottom, rule[0], rule) is None:
                break
            bottom = rule[0]
        # Everything the frame then holds within the table's width: blocks
        # in the regions just walked, a block or table fragment running over
        # several of its rows, and blocks lying beside the table's own rows
        # that detection left out (the pin description fixture's nested
        # status columns).
        x0 = min(r[1] for r in rules)
        x1 = max(r[2] for r in rules)
        taken = [
            b for b in blocks
            if _bbox(b).y0 >= top - tol and _bbox(b).y1 <= bottom + tol
            and _bbox(b).x0 >= x0 - tol and _bbox(b).x1 <= x1 + tol
        ]
        if not taken:
            return

        def rows_of(block: Any) -> List[List[TableCell]]:
            return block.grid if isinstance(block, TableBlock) else _rows_from_block(block)

        def row_y(row: List[TableCell]) -> float:
            ys = [_cell_y0(c) for c in row if c.visual_layout]
            return min(ys) if ys else 0.0

        grid = sorted(
            list(table.grid) + [row for b in taken for row in rows_of(b)], key=row_y
        )
        grid = _merge_orphan_rows(grid)
        _infer_rowspans(grid)
        table.grid = grid
        table.row_count = len(grid)
        table.column_count = max((len(r) for r in grid), default=0)
        table.span_map = _build_span_map(grid)
        boxes = [c.visual_layout.bounding_box for r in grid for c in r if c.visual_layout]
        table.visual_layout = VisualLayout(
            bounding_box=NormalizedRect(
                x0=min(b.x0 for b in boxes), y0=min(b.y0 for b in boxes),
                x1=max(b.x1 for b in boxes), y1=max(b.y1 for b in boxes),
            ),
            page_or_screen_index=table.visual_layout.page_or_screen_index,
        )
        for b in taken:
            b.is_tombstoned = True
            if not b.metadata:
                b.metadata = {}
            b.metadata["tombstone_reason"] = (
                "merged_into_adjacent_table" if isinstance(b, TableBlock) else "merged_into_table_frame"
            )

    def _mark_borders(self, doc: KnowledgeDocument) -> None:
        """Mark each cell's own edges from the rules printed on the source.

        The grid lines are most of a ruled table's ink, and they are not in
        the KRM any other way: on these sources they are not vector strokes
        the adapter could carry over (page.get_drawings() returns nothing -
        the pages are scans), so the only place they exist is the rendered
        pixels. A table rebuilt without them is visibly a different object
        from the one on the page.

        Which edges are drawn is read, not assumed, and it genuinely
        differs between sources: the decimal/binary page rules only under
        its header, the voltage-regulator page under every row. Each cell
        is asked about its own four sides (TableCell.border_*), so a rule
        that covers part of a boundary stays attached to the cells it
        actually touches.

        Best-effort by design - no source file, no pixels, or no numpy and
        the cells simply keep their borders off, and the renderer falls
        back to its own default.
        """
        path = resolve_source_path(doc)
        if not path:
            return
        try:
            import numpy as np
            import pymupdf
        except ImportError:
            return

        tables: List[TableBlock] = []

        def collect(container: ContainerUnit) -> None:
            for child in container.children:
                if isinstance(child, ContainerUnit):
                    collect(child)
                elif isinstance(child, TableBlock) and not child.is_tombstoned and not _is_box_table(child):
                    tables.append(child)

        for root in doc.root_containers:
            collect(root)
        if not tables:
            return

        try:
            source = pymupdf.open(path)
        except Exception:
            return
        try:
            for table in tables:
                vl = table.visual_layout
                if vl is None or vl.bounding_box is None:
                    continue
                page_index = vl.page_or_screen_index or 0
                if page_index >= source.page_count:
                    continue
                _mark_fill(np, pymupdf, source[page_index], table)
                _mark_text_colour(np, pymupdf, source[page_index], table)
                _find_placeholder_marks(np, pymupdf, source[page_index], table)
                _drop_leaders(np, pymupdf, source[page_index], table)
                _marks_on_leaders(table)
                _reseat_stacked_lines(np, pymupdf, source[page_index], table)
                _deflate_boxes(np, pymupdf, source[page_index], table)
                _measure_leader_grid(np, pymupdf, source[page_index], table)
                _mark_italic(np, pymupdf, source[page_index], table)
                _mark_printed_width(source[page_index], table)
                _mark_typeface(np, pymupdf, source[page_index], table)
                _size_display_type(np, pymupdf, source[page_index], table)
                _mark_cell_borders(np, pymupdf, source[page_index], table)
                _regrid_ruled_bands(source[page_index], table)
                _split_cells_at_rules(source[page_index], table)
                _fold_label_rows(table)
        finally:
            source.close()

    def _process_container(self, container: ContainerUnit) -> None:
        for child in list(container.children):
            if isinstance(child, ContainerUnit):
                self._process_container(child)

        para_blocks: List[Tuple[int, ParagraphBlock]] = []
        separator_indices: set = set()
        # a line's usual height on this container's pages, from its blocks of one line
        one_line = sorted(
            _bbox(c).y1 - _bbox(c).y0 for c in container.children
            if isinstance(c, (ParagraphBlock, UnknownBlock)) and not getattr(c, "is_tombstoned", False)
            and _bbox(c) is not None and len(getattr(c, "inlines", None) or []) == 1
        )
        usual_height = one_line[len(one_line) // 2] if one_line else 0.0
        for idx, child in enumerate(container.children):
            # RFC 0014: blocks already merged into a table on an earlier run are
            # tombstoned. Collecting them again would cluster the same run twice
            # and insert a duplicate TableBlock — with an identical derived id.
            if getattr(child, "is_tombstoned", False):
                continue
            if isinstance(child, (ParagraphBlock, UnknownBlock)) and _bbox(child) is not None and _page_idx(child) is not None:
                text = _get_text(child)
                bb = _bbox(child)
                if _looks_like_separator(text):
                    separator_indices.add(idx)
                    continue
                if _is_leader_residue(text, bb.y1 - bb.y0, usual_height):
                    continue
                if (bb.y1 - bb.y0) > MAX_BLOCK_HEIGHT:
                    continue
                if len(text) > MAX_CELL_TEXT_LEN:
                    continue
                para_blocks.append((idx, child))

        if len(para_blocks) < MIN_TABLE_ROWS:
            self._detect_single_block_tables(container)
            return

        pages: Dict[int, List[Tuple[int, ParagraphBlock]]] = {}
        for idx, block in para_blocks:
            pg = _page_idx(block)
            pages.setdefault(pg, []).append((idx, block))

        indices_to_remove: set = set()
        replacements: Dict[int, TableBlock] = {}

        for page_num, page_blocks in pages.items():
            columns = _absorb_stray_columns(_cluster_columns(page_blocks))

            for column in columns:
                runs = _find_table_runs(column)
                for run in runs:
                    if not run:
                        continue

                    # A run's own y-step consistency test doesn't see column
                    # structure, so an ordinary line of preamble sitting
                    # directly above a real table - just as evenly spaced as
                    # the table rows below it - can be collected into the
                    # same run (found on the messy voltage-regulator
                    # fixture: "jiA7812 ELECTRICAL CHARACTERISTICS: V,N - 19
                    # V. ..." AND, once that longer sentence was trimmed, a
                    # second, shorter stray line "unltSI other**** fpttlf'
                    # td." that a length ceiling alone can't tell apart from
                    # a real short table row). What actually distinguishes
                    # them from real content is column structure elsewhere
                    # in the SAME run: a genuine single-column table (one
                    # text block per row, no per-line geometry to split at
                    # all, as in test_table_detector's synthetic rows) never
                    # produces a multi-cell row anywhere, so leaving a run
                    # like that untouched is safe regardless of any one
                    # row's length. A run that DOES contain real multi-cell
                    # rows further down is a real table with stray
                    # single-cell junk stuck to its front, whatever that
                    # junk's own length - trim every leading single-cell
                    # block there, of any length, down to the first
                    # multi-cell one.
                    # `run` is now a list of ROW-GROUPS (_find_table_runs /
                    # _group_column_by_row) - one or more sibling blocks
                    # sharing a visual row, not one block per row. A row's
                    # own cells come from _rows_from_group, which merges a
                    # multi-block group's fragments by x0 instead of
                    # dropping every block after the first at that y0
                    # (RFC 0001 SS2.4).
                    group_rows = [(group, _rows_from_group(group)) for group in run]
                    has_multi_cell_row = any(
                        len(r) > 1 for _, rows in group_rows for r in rows
                    )
                    while (
                        group_rows
                        and has_multi_cell_row
                        and all(len(r) <= 1 for r in group_rows[0][1])
                    ):
                        group_rows.pop(0)
                    run = [group for group, _ in group_rows]
                    precomputed_rows = [rows for _, rows in group_rows]
                    if len(run) < MIN_TABLE_ROWS:
                        continue

                    flat_blocks = [item for group in run for item in group]
                    first_idx = min(orig_idx for orig_idx, _ in flat_blocks)

                    # Accept/reject on the run as clustered (one candidate per
                    # visual row) - unaffected by _rows_from_group later
                    # possibly expanding one row into several grid rows
                    # (a rowspan, or a wrapped line). Deciding on the
                    # post-expansion row count let a wrapped 2-line sentence
                    # push an ordinary caption+paragraph+exercise+page-number
                    # group over the row_count>=5 threshold and get accepted
                    # as a "table" - RFC 0001 §2.4 exists for exactly this
                    # kind of silent misclassification.
                    row_count = len(run)
                    run_indices = {orig_idx for orig_idx, _ in flat_blocks}
                    has_separators = bool(separator_indices & {i - 1 for i in run_indices} |
                                         separator_indices & {i + 1 for i in run_indices})

                    is_single_col = all(
                        _count_columns(_get_text(b)) <= 1 for _, b in flat_blocks
                    )
                    avg_text_len = sum(len(_get_text(b).strip()) for _, b in flat_blocks) / max(1, row_count)
                    if is_single_col and row_count < 5 and not has_separators:
                        continue
                    if is_single_col and avg_text_len < 15 and not has_separators:
                        continue

                    grid: List[List[TableCell]] = []
                    for rows in precomputed_rows:
                        grid.extend(rows)
                    # A column of paragraphs, evenly spaced, is no table.
                    if _reads_as_prose([
                        [(_cell_text(c), c.visual_layout.bounding_box if c.visual_layout else None) for c in row]
                        for row in grid
                    ]):
                        continue

                    grid = _merge_orphan_rows(grid)

                    _infer_rowspans(grid)

                    sep_boost = 0.10 if has_separators else 0.0
                    col_penalty = 0.15 if is_single_col else 0.0
                    cls_conf = min(0.90, 0.50 + row_count * 0.05 + sep_boost - col_penalty)
                    avg_ext = sum(
                        b.extraction_confidence for _, b in flat_blocks
                    ) / len(flat_blocks)
                    first_block = run[0][0][1]
                    # The table's own box is the union of its cells, not just
                    # the first accepted row's block wholesale - a cross-block
                    # table can run to dozens of rows below that first one,
                    # and using only its bbox left the table's box only as
                    # tall as a single row (found while building a visual
                    # diff tool: cropping a table by its own visual_layout
                    # produced a sliver a few points tall instead of the
                    # whole table - RFC 0002's TableBlock has always been
                    # more than that first block's own geometry).
                    cell_boxes = [
                        c.visual_layout.bounding_box for r in grid for c in r if c.visual_layout
                    ]
                    if cell_boxes:
                        visual_layout = VisualLayout(
                            bounding_box=NormalizedRect(
                                x0=min(b.x0 for b in cell_boxes), y0=min(b.y0 for b in cell_boxes),
                                x1=max(b.x1 for b in cell_boxes), y1=max(b.y1 for b in cell_boxes),
                            ),
                            page_or_screen_index=first_block.visual_layout.page_or_screen_index
                            if first_block.visual_layout else 0,
                        )
                    else:
                        visual_layout = first_block.visual_layout

                    span_map = _build_span_map(grid)

                    table = TableBlock(
                        id=derive_composite_id(
                            "table", *[b.id for _, b in flat_blocks]
                        ),
                        grid=grid,
                        row_count=len(grid),
                        column_count=max((len(r) for r in grid), default=0),
                        parent_container_id=container.id,
                        provenance_info=first_block.provenance_info,
                        visual_layout=visual_layout,
                        extraction_confidence=avg_ext,
                        classification_confidence=cls_conf,
                        confidence_score=min(avg_ext, cls_conf),
                        span_map=span_map,
                    )
                    replacements[first_idx] = table
                    # Only now, with a table to hold them: marking the rows
                    # before the validation below meant a rejected run left its
                    # blocks tombstoned with nothing to absorb them — silent
                    # deletion, which RFC 0001 §2.4 exists to prevent.
                    indices_to_remove |= run_indices
                    self._table_count += 1

        # Tombstone separators adjacent to detected tables
        for sep_idx in separator_indices:
            if (sep_idx - 1) in indices_to_remove or (sep_idx + 1) in indices_to_remove:
                indices_to_remove.add(sep_idx)

        if indices_to_remove:
            # RFC 0001 §2.4 / 0005 §2: no physical deletion. Rows absorbed into the
            # table are tombstoned in place (exporters skip them); the table block
            # is inserted.
            new_children = []
            for idx, child in enumerate(container.children):
                if idx in replacements:
                    new_children.append(replacements[idx])
                if idx in indices_to_remove:
                    child.is_tombstoned = True
                    if not child.metadata:
                        child.metadata = {}
                    child.metadata["tombstone_reason"] = "merged_into_table"
                new_children.append(child)
            container.children = new_children

        self._detect_single_block_tables(container)
        self._merge_adjacent_tables(container)

    def _merge_adjacent_tables(self, container: ContainerUnit) -> None:
        """Fold a run of TableBlocks with nothing real between them into one.

        The two detection passes above see the page's own block boundaries,
        not the table's true extent: a single logical table (one bordered
        box in the source, RFC 0008 §5.2 - the adapter cannot tell them it
        is one table) can straddle both paths when the source mixes
        granularity - most of its rows arrive as one-line siblings the
        cross-block path clusters, but one sibling packs several rows into
        one block (over MAX_CELL_TEXT_LEN once flattened, so the cross-block
        collector skips it) and only the single-block path catches that
        piece, as its own separate TableBlock right next to the first.

        A short stray line between two such fragments (its own row that
        neither pass claimed) is absorbed into the run too, via the same
        _rows_from_block reader used elsewhere; anything long enough to be
        real prose stops the run, so this can't swallow unrelated content.
        """
        children = container.children
        i = 0
        while i < len(children):
            if not isinstance(children[i], TableBlock) or _is_box_table(children[i]):
                i += 1
                continue
            base = children[i]
            merged_grid: List[List[TableCell]] = list(base.grid)
            boxes = [c.visual_layout.bounding_box for r in merged_grid for c in r if c.visual_layout]
            consumed: List[int] = []
            # A short line only counts as a stray row when another table
            # fragment follows it: held here until one does, dropped if the
            # run ends first. Absorbing it on sight turned any short line
            # AFTER a table - the next section's heading, a source note -
            # into a table row.
            pending_rows: List[List[TableCell]] = []
            pending_idx: List[int] = []
            j = i + 1
            while j < len(children):
                nxt = children[j]
                if getattr(nxt, "is_tombstoned", False):
                    j += 1
                    continue
                # A table never continues onto another page by adjacency in
                # children alone: two tables on facing pages with nothing
                # between them were merged into one whose box mixed the two
                # pages' coordinates.
                if _page_idx(nxt) != _page_idx(base):
                    break
                if _is_box_table(nxt):
                    break
                if isinstance(nxt, TableBlock):
                    merged_grid.extend(pending_rows)
                    consumed.extend(pending_idx)
                    pending_rows, pending_idx = [], []
                    merged_grid.extend(nxt.grid)
                    if nxt.visual_layout:
                        boxes.append(nxt.visual_layout.bounding_box)
                    consumed.append(j)
                    j += 1
                    continue
                next_text = _get_text(nxt) if isinstance(nxt, (ParagraphBlock, UnknownBlock)) else ""
                if (
                    isinstance(nxt, (ParagraphBlock, UnknownBlock))
                    and len(next_text) <= MAX_CELL_TEXT_LEN // 2
                    and not _CAPTION_RE.match(next_text.strip())
                ):
                    pending_rows.extend(_rows_from_block(nxt))
                    pending_idx.append(j)
                    j += 1
                    continue
                break
            if not consumed:
                i += 1
                continue
            base.grid = merged_grid
            # Recomputed over the merged grid: the fragments' own maps
            # indexed their own rows, and base's alone no longer covers it.
            base.span_map = _build_span_map(merged_grid)
            base.row_count = len(merged_grid)
            base.column_count = max((len(r) for r in merged_grid), default=0)
            if boxes and base.visual_layout:
                base.visual_layout = VisualLayout(
                    bounding_box=NormalizedRect(
                        x0=min(b.x0 for b in boxes), y0=min(b.y0 for b in boxes),
                        x1=max(b.x1 for b in boxes), y1=max(b.y1 for b in boxes),
                    ),
                    page_or_screen_index=base.visual_layout.page_or_screen_index,
                )
            for k in consumed:
                children[k].is_tombstoned = True
                if not children[k].metadata:
                    children[k].metadata = {}
                children[k].metadata["tombstone_reason"] = (
                    "merged_into_adjacent_table" if isinstance(children[k], TableBlock)
                    else "merged_into_table_row"
                )
            i = j

    def _detect_single_block_tables(self, container: ContainerUnit) -> None:
        """A table can also arrive as ONE block whose own lines are the rows
        (a PDF text layer that groups a boxed table into a single block —
        RFC 0008 §5.2 forbids the adapter from splitting it further).

        Run after the cross-block path above, on whatever it left untouched:
        a block that individually looks tabular can also be one row of a
        larger run the cross-block path would otherwise have assembled
        correctly (RFC 0009 §5.2 — analyzers still apply in a fixed order,
        but within this one detector the coarser, better-tested grouping
        gets first claim on each block). A block that isn't a table is
        returned untouched, so ordinary paragraphs never get here.
        """
        for idx, child in enumerate(container.children):
            if getattr(child, "is_tombstoned", False):
                continue
            if not isinstance(child, (ParagraphBlock, UnknownBlock)):
                continue
            table = _table_from_lines(child)
            if table is not None:
                header_idx = idx - 1
                if header_idx >= 0:
                    header_block = container.children[header_idx]
                    if (
                        not getattr(header_block, "is_tombstoned", False)
                        and isinstance(header_block, (ParagraphBlock, UnknownBlock))
                    ):
                        header_row = _header_row_for_block(header_block)
                        if header_row is not None:
                            # The table's own box has to reflect where the
                            # header actually printed in the SOURCE, not
                            # where _snap_row_to_columns relocates it for
                            # LaTeX column-binning - confirmed directly on
                            # the decimal/binary fixture: "Decimal"'s real
                            # glyph sits at x0=0.3013, snapping moves that
                            # cell's OWN bbox to the nearest body column
                            # (0.3563, 5.5pt of page width away) so LaTeX
                            # groups it with the right output column, but
                            # using that SAME relocated box for the table's
                            # bounding_box quietly shrank it by that same
                            # 5.5pt - and every consumer that crops the
                            # SOURCE page by this table's own bbox (the
                            # visual-overlay test included) then crops off
                            # part of the header before ever comparing
                            # anything. Snapshot the true boxes first.
                            header_boxes = [
                                c.visual_layout.bounding_box for c in header_row
                                if c.visual_layout
                            ]
                            header_row = _snap_row_to_columns(header_row, table.grid)
                            table.grid.insert(0, header_row)
                            table.row_count = len(table.grid)
                            table.column_count = max(table.column_count, len(header_row))
                            if header_boxes and table.visual_layout:
                                old = table.visual_layout.bounding_box
                                table.visual_layout = VisualLayout(
                                    bounding_box=NormalizedRect(
                                        x0=min(old.x0, min(b.x0 for b in header_boxes)),
                                        y0=min(old.y0, min(b.y0 for b in header_boxes)),
                                        x1=max(old.x1, max(b.x1 for b in header_boxes)),
                                        y1=max(old.y1, max(b.y1 for b in header_boxes)),
                                    ),
                                    page_or_screen_index=table.visual_layout.page_or_screen_index,
                                )
                            header_block.is_tombstoned = True
                            if not header_block.metadata:
                                header_block.metadata = {}
                            header_block.metadata["tombstone_reason"] = "merged_into_table_header"
                container.children[idx] = table
                self._table_count += 1
