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

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
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

MIN_TABLE_ROWS = 3
Y_STEP_TOLERANCE = 0.012
X_OVERLAP_THRESHOLD = 0.25
MAX_CELL_TEXT_LEN = 120
MAX_BLOCK_HEIGHT = 0.05


_SEPARATOR_RE = re.compile(r"^[\s\-_=|+:·.─━┃│┼┤├┬┴]{3,}$")
_TAB_SPLIT_RE = re.compile(r"\t|  {2,}|(?:\s{2,}\|?\s{2,})")


def _looks_like_separator(text: str) -> bool:
    return bool(_SEPARATOR_RE.match(text.strip()))


def _count_columns(text: str) -> int:
    parts = _TAB_SPLIT_RE.split(text.strip())
    return len([p for p in parts if p.strip()])


def _has_table_font_role(block: ParagraphBlock) -> bool:
    md = getattr(block, "metadata", None) or {}
    return md.get("font_role") in ("body", "caption", "code")


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
        for container in doc.root_containers:
            self._process_container(container)
        if self._table_count:
            log.info("TableDetectorAnalyzer: %d table(s) detected", self._table_count)

    def _process_container(self, container: ContainerUnit) -> None:
        for child in list(container.children):
            if isinstance(child, ContainerUnit):
                self._process_container(child)

        para_blocks: List[Tuple[int, ParagraphBlock]] = []
        separator_indices: set = set()
        for idx, child in enumerate(container.children):
            if isinstance(child, ParagraphBlock) and _bbox(child) is not None and _page_idx(child) is not None:
                text = _get_text(child)
                bb = _bbox(child)
                if _looks_like_separator(text):
                    separator_indices.add(idx)
                    continue
                if (bb.y1 - bb.y0) > MAX_BLOCK_HEIGHT:
                    continue
                if len(text) > MAX_CELL_TEXT_LEN:
                    continue
                para_blocks.append((idx, child))

        if len(para_blocks) < MIN_TABLE_ROWS:
            return

        pages: Dict[int, List[Tuple[int, ParagraphBlock]]] = {}
        for idx, block in para_blocks:
            pg = _page_idx(block)
            pages.setdefault(pg, []).append((idx, block))

        indices_to_remove: set = set()
        replacements: Dict[int, TableBlock] = {}

        for page_num, page_blocks in pages.items():
            columns = _cluster_columns(page_blocks)

            for column in columns:
                runs = _find_table_runs(column)
                for run in runs:
                    if not run:
                        continue

                    grid: List[List[TableCell]] = []
                    first_idx = run[0][0]

                    for orig_idx, block in run:
                        text = _get_text(block)
                        cell = TableCell(
                            content=[
                                ParagraphBlock(
                                    inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
                                )
                            ]
                        )
                        grid.append([cell])
                        indices_to_remove.add(orig_idx)

                    row_count = len(grid)
                    run_indices = {orig_idx for orig_idx, _ in run}
                    has_separators = bool(separator_indices & {i - 1 for i in run_indices} |
                                         separator_indices & {i + 1 for i in run_indices})

                    is_single_col = all(
                        _count_columns(_get_text(b)) <= 1 for _, b in run
                    )
                    avg_text_len = sum(len(_get_text(b).strip()) for _, b in run) / max(1, row_count)
                    if is_single_col and row_count < 5 and not has_separators:
                        continue
                    if is_single_col and avg_text_len < 15 and not has_separators:
                        continue

                    sep_boost = 0.10 if has_separators else 0.0
                    col_penalty = 0.15 if is_single_col else 0.0
                    cls_conf = min(0.90, 0.50 + row_count * 0.05 + sep_boost - col_penalty)
                    avg_ext = sum(
                        b.extraction_confidence for _, b in run
                    ) / len(run)
                    table = TableBlock(
                        grid=grid,
                        parent_container_id=container.id,
                        provenance_info=run[0][1].provenance_info,
                        visual_layout=run[0][1].visual_layout,
                        extraction_confidence=avg_ext,
                        classification_confidence=cls_conf,
                        confidence_score=min(avg_ext, cls_conf),
                    )
                    replacements[first_idx] = table
                    self._table_count += 1

        # Tombstone separators adjacent to detected tables
        for sep_idx in separator_indices:
            if (sep_idx - 1) in indices_to_remove or (sep_idx + 1) in indices_to_remove:
                indices_to_remove.add(sep_idx)

        if not indices_to_remove:
            return

        # RFC 0001 §2.4 / 0005 §2: no physical deletion. Rows absorbed into the table
        # are tombstoned in place (exporters skip them); the table block is inserted.
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
