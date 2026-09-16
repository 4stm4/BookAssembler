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
from src.analyzers.table.signals import MAX_BLOCK_HEIGHT, MAX_CELL_TEXT_LEN, MIN_TABLE_ROWS, log
from src.analyzers.table.rules import _absorb_stray_columns, _bbox, _cluster_columns, _count_columns, _find_table_runs, _get_text, _header_row_for_block, _looks_like_separator, _mark_cell_borders, _page_idx, _rows_from_block, _rows_from_group, _snap_row_to_columns, _table_from_lines

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
        self._mark_borders(doc)

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
                elif isinstance(child, TableBlock) and not child.is_tombstoned:
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
                _mark_cell_borders(np, pymupdf, source[page_index], table)
        finally:
            source.close()

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
            if not isinstance(children[i], TableBlock):
                i += 1
                continue
            base = children[i]
            merged_grid: List[List[TableCell]] = list(base.grid)
            boxes = [c.visual_layout.bounding_box for r in merged_grid for c in r if c.visual_layout]
            consumed: List[int] = []
            j = i + 1
            while j < len(children):
                nxt = children[j]
                if getattr(nxt, "is_tombstoned", False):
                    j += 1
                    continue
                if isinstance(nxt, TableBlock):
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
                    extra_rows = _rows_from_block(nxt)
                    if extra_rows:
                        merged_grid.extend(extra_rows)
                        consumed.append(j)
                        j += 1
                        continue
                break
            if not consumed:
                i += 1
                continue
            base.grid = merged_grid
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
