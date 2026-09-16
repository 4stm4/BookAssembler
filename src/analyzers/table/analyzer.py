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

from src.analyzers.table.signals import MAX_BLOCK_HEIGHT, MAX_CELL_TEXT_LEN, MIN_TABLE_ROWS, log
from src.analyzers.table.rules import _bbox, _cluster_columns, _count_columns, _find_table_runs, _get_text, _header_row_for_block, _looks_like_separator, _page_idx, _rows_from_block, _snap_row_to_columns, _table_from_lines

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
            columns = _cluster_columns(page_blocks)

            for column in columns:
                runs = _find_table_runs(column)
                for run in runs:
                    if not run:
                        continue

                    first_idx = run[0][0]

                    # Accept/reject on the run as clustered (one candidate per
                    # sibling block) - unaffected by _rows_from_block later
                    # possibly expanding one sibling into several grid rows
                    # (a rowspan, or a wrapped line). Deciding on the
                    # post-expansion row count let a wrapped 2-line sentence
                    # push an ordinary caption+paragraph+exercise+page-number
                    # group over the row_count>=5 threshold and get accepted
                    # as a "table" - RFC 0001 §2.4 exists for exactly this
                    # kind of silent misclassification.
                    row_count = len(run)
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

                    grid: List[List[TableCell]] = []
                    for orig_idx, block in run:
                        grid.extend(_rows_from_block(block))

                    sep_boost = 0.10 if has_separators else 0.0
                    col_penalty = 0.15 if is_single_col else 0.0
                    cls_conf = min(0.90, 0.50 + row_count * 0.05 + sep_boost - col_penalty)
                    avg_ext = sum(
                        b.extraction_confidence for _, b in run
                    ) / len(run)
                    table = TableBlock(
                        id=derive_composite_id(
                            "table", *[b.id for _, b in run]
                        ),
                        grid=grid,
                        row_count=len(grid),
                        column_count=max((len(r) for r in grid), default=0),
                        parent_container_id=container.id,
                        provenance_info=run[0][1].provenance_info,
                        visual_layout=run[0][1].visual_layout,
                        extraction_confidence=avg_ext,
                        classification_confidence=cls_conf,
                        confidence_score=min(avg_ext, cls_conf),
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
                            header_row = _snap_row_to_columns(header_row, table.grid)
                            table.grid.insert(0, header_row)
                            table.row_count = len(table.grid)
                            table.column_count = max(table.column_count, len(header_row))
                            header_boxes = [
                                c.visual_layout.bounding_box for c in header_row
                                if c.visual_layout
                            ]
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
