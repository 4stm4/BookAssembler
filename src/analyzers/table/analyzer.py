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
    StyledTextSpan,
    TableBlock,
    TableCell,
    TextLineInline,
)

from src.analyzers.table.signals import MAX_BLOCK_HEIGHT, MAX_CELL_TEXT_LEN, MIN_TABLE_ROWS, log
from src.analyzers.table.rules import _bbox, _cluster_columns, _count_columns, _find_table_runs, _get_text, _looks_like_separator, _page_idx

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
                        id=derive_composite_id(
                            "table", *[b.id for _, b in run]
                        ),
                        grid=grid,
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
