"""
TableDetectorAnalyzer — detects tabular structures by spatial alignment.

Per RFC 0005 (TableAnalyzer): READ, TRANSFORM_NODE, INSERT permissions on KRM.
Finds runs of vertically equidistant ParagraphBlocks sharing the same page
and overlapping x-ranges, then replaces them with a single TableBlock.

Algorithm:
1. Walk all containers collecting ParagraphBlocks that have VisualLayout.
2. Group blocks by (page_index, x-column cluster).
3. Within each group, find runs of 3+ blocks with consistent y-step.
4. Replace the run with a TableBlock where each row is a TableCell.
5. If multiple column clusters share the same y-rows, merge into a
   multi-column table.
"""

from src.analyzers.table.signals import MAX_BLOCK_HEIGHT, MAX_CELL_TEXT_LEN, MIN_TABLE_ROWS, X_OVERLAP_THRESHOLD, Y_STEP_TOLERANCE, _SEPARATOR_RE, _TAB_SPLIT_RE, log
from src.analyzers.table.rules import _bbox, _cluster_columns, _count_columns, _find_table_runs, _get_text, _has_table_font_role, _looks_like_separator, _page_idx, _x_overlaps
from src.analyzers.table.analyzer import TableDetectorAnalyzer

__all__ = [
    "MAX_BLOCK_HEIGHT",
    "MAX_CELL_TEXT_LEN",
    "MIN_TABLE_ROWS",
    "TableDetectorAnalyzer",
    "X_OVERLAP_THRESHOLD",
    "Y_STEP_TOLERANCE",
    "_SEPARATOR_RE",
    "_TAB_SPLIT_RE",
    "_bbox",
    "_cluster_columns",
    "_count_columns",
    "_find_table_runs",
    "_get_text",
    "_has_table_font_role",
    "_looks_like_separator",
    "_page_idx",
    "_x_overlaps",
    "log",
]
