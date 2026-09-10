"""table: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.table.signals import MAX_BLOCK_HEIGHT, MAX_CELL_TEXT_LEN, MIN_TABLE_ROWS, X_OVERLAP_THRESHOLD, Y_STEP_TOLERANCE, _SEPARATOR_RE, _TAB_SPLIT_RE, log
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
