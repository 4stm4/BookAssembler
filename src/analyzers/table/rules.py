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

def _find_table_runs(blocks_with_idx: List[Tuple[int, ParagraphBlock]]) -> List[List[Tuple[int, ParagraphBlock]]]:
    """Find runs of blocks with consistent vertical spacing."""
    if len(blocks_with_idx) < MIN_TABLE_ROWS:
        return []

    sorted_blocks = sorted(blocks_with_idx, key=lambda t: _bbox(t[1]).y0)

    runs: List[List[Tuple[int, ParagraphBlock]]] = []
    current_run: List[Tuple[int, ParagraphBlock]] = [sorted_blocks[0]]
    current_step: Optional[float] = None

    for i in range(1, len(sorted_blocks)):
        prev_bb = _bbox(sorted_blocks[i - 1][1])
        curr_bb = _bbox(sorted_blocks[i][1])
        step = curr_bb.y0 - prev_bb.y0

        if step < 0.005:
            continue

        if current_step is None:
            current_step = step
            current_run.append(sorted_blocks[i])
        elif abs(step - current_step) < Y_STEP_TOLERANCE:
            current_run.append(sorted_blocks[i])
        else:
            if len(current_run) >= MIN_TABLE_ROWS:
                runs.append(current_run)
            current_run = [sorted_blocks[i]]
            current_step = None

    if len(current_run) >= MIN_TABLE_ROWS:
        runs.append(current_run)

    return runs

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
        rows.append((text, bbox, style))
    return rows


def _make_cell(
    text: str, bbox: Optional[NormalizedRect], style: Optional[Any],
    page_idx: Optional[int], row_span: int = 1,
) -> "TableCell":
    return TableCell(
        row_span=row_span,
        content=[ParagraphBlock(
            inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        )],
        visual_layout=VisualLayout(
            bounding_box=bbox, page_or_screen_index=page_idx or 0, style=style,
        ) if bbox is not None else None,
    )


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
    if not fragments:
        text = _get_text(block)
        return [[_make_cell(text, None, None, None)]]

    page_idx = _page_idx(block)
    sub_rows = _group_into_rows(fragments)

    if len(sub_rows) <= 1:
        row = sub_rows[0] if sub_rows else fragments
        row = sorted(row, key=lambda item: item[1].x0 if item[1] is not None else 0.0)
        return [[_make_cell(t, b, s, page_idx) for t, b, s in row]]

    # A real rowspan needs the LATER sub-rows to be genuine multi-column data
    # rows continuing this one, not just the next unrelated line of prose
    # that happens to share this block (e.g. a title line "jiA7812" directly
    # above an unrelated paragraph line - one fragment each, nothing in
    # common). Require every sub-row after the first to carry at least 2
    # fragments of its own before treating a first-row-only column as shared.
    looks_like_continuation = all(len(r) >= 2 for r in sub_rows[1:])

    bins = _local_column_bins(fragments)
    # column index -> {sub_row index -> (text, bbox, style)}
    by_col: Dict[int, Dict[int, Tuple[str, Optional[NormalizedRect], Optional[Any]]]] = {}
    for sr_idx, sub_row in enumerate(sub_rows):
        for text, bbox, style in sub_row:
            col = _nearest_bin(bbox.x0, bins) if bbox is not None else 0
            by_col.setdefault(col, {})[sr_idx] = (text, bbox, style)

    rows: List[List[TableCell]] = [[] for _ in sub_rows]
    for col in sorted(by_col):
        occupied = by_col[col]
        if len(occupied) == 1 and 0 in occupied and len(sub_rows) > 1 and looks_like_continuation:
            # Populated only in the first sub-row: a real rowspan.
            text, bbox, style = occupied[0]
            rows[0].append(_make_cell(text, bbox, style, page_idx, row_span=len(sub_rows)))
            continue
        for sr_idx in sorted(occupied):
            text, bbox, style = occupied[sr_idx]
            rows[sr_idx].append(_make_cell(text, bbox, style, page_idx))

    for row in rows:
        row.sort(key=lambda c: c.visual_layout.bounding_box.x0 if c.visual_layout else 0.0)
    return rows


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

    for item in grouped:
        item.sort(key=lambda tb: tb[1].x0)

    grouped.extend([item] for item in without_bbox)
    return grouped


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
    table = TableBlock(
        grid=grid,
        parent_container_id=block.parent_container_id,
        provenance_info=block.provenance_info,
        visual_layout=VisualLayout(
            bounding_box=table_bbox or _bbox(block),
            page_or_screen_index=page_idx or 0,
        ) if table_bbox else block.visual_layout,
        extraction_confidence=block.extraction_confidence,
        classification_confidence=cls_conf,
        confidence_score=min(block.extraction_confidence, cls_conf),
    )
    table.id = block.id  # RFC 0001 §2.3: reclassification keeps identity
    return table


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
