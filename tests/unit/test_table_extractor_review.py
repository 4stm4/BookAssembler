"""Regressions for defects found in the table extractor code review."""
from src.analyzers.table.analyzer import TableDetectorAnalyzer
from src.krm.models import (
    ContainerUnit, NormalizedRect, ParagraphBlock, StyledTextSpan,
    TableBlock, TableCell, TextLineInline, VisualLayout,
)


def _para(text, y0=0.5, x0=0.1, x1=0.4, page=0):
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=x0, y0=y0, x1=x1, y1=y0 + 0.01),
            page_or_screen_index=page,
        ),
    )


def _cell(text, x0=0.1, y0=0.5, page=0):
    return TableCell(
        content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=x0, y0=y0, x1=x0 + 0.05, y1=y0 + 0.01),
            page_or_screen_index=page,
        ),
    )


def _table(rows, y0=0.5, page=0):
    grid = [[_cell(t, x0=0.1 + 0.1 * c, y0=y0 + 0.02 * r, page=page)
             for c, t in enumerate(row)] for r, row in enumerate(rows)]
    return TableBlock(
        grid=grid, row_count=len(grid), column_count=max(len(r) for r in grid),
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=0.1, y0=y0, x1=0.4, y1=y0 + 0.02 * len(grid)),
            page_or_screen_index=page,
        ),
    )


class TestMergeAdjacentTables:
    def test_short_line_after_last_table_is_not_absorbed(self):
        table = _table([["1", "2"], ["3", "4"]])
        heading = _para("1.3 Octal numbers", y0=0.6)
        c = ContainerUnit(title="ch", children=[table, heading])
        TableDetectorAnalyzer()._merge_adjacent_tables(c)
        assert not heading.is_tombstoned
        assert table.row_count == 2

    def test_short_line_between_two_tables_is_absorbed(self):
        first = _table([["1", "2"], ["3", "4"]])
        stray = _para("5 6", y0=0.55)
        second = _table([["7", "8"]], y0=0.57)
        c = ContainerUnit(title="ch", children=[first, stray, second])
        TableDetectorAnalyzer()._merge_adjacent_tables(c)
        assert stray.is_tombstoned and second.is_tombstoned
        assert first.row_count == 4

    def test_tables_on_different_pages_are_not_merged(self):
        first = _table([["1", "2"], ["3", "4"]], page=0)
        second = _table([["5", "6"]], y0=0.1, page=1)
        c = ContainerUnit(title="ch", children=[first, second])
        TableDetectorAnalyzer()._merge_adjacent_tables(c)
        assert not second.is_tombstoned
        assert first.row_count == 2

    def test_merged_table_span_map_covers_the_merged_rows(self):
        first = _table([["1", "2"], ["3", "4"]])
        second = _table([["5", "6"], ["7"]], y0=0.55)
        second.grid[0][1].row_span = 2
        c = ContainerUnit(title="ch", children=[first, second])
        TableDetectorAnalyzer()._merge_adjacent_tables(c)
        assert first.row_count == 4
        assert first.span_map.get((3, 1)) == (2, 1)


class TestFindTableRuns:
    def test_first_row_after_a_heading_is_kept(self):
        from src.analyzers.table.rules import _find_table_runs
        blocks = [(0, _para("Heading", y0=0.10))] + [
            (i + 1, _para(f"{i} {i * 2}", y0=0.15 + 0.02 * i)) for i in range(3)
        ]
        runs = _find_table_runs(blocks)
        assert len(runs) == 1
        assert [g[0][0] for g in runs[0]] == [1, 2, 3]

    def test_group_just_under_its_row_joins_the_run(self):
        from src.analyzers.table.rules import _find_table_runs
        blocks = [
            (0, _para("0 0", y0=0.10)),
            (1, _para("1 2", y0=0.12)),
            (2, _para("note", y0=0.124, x0=0.2)),  # 0.004 under row 1
            (3, _para("2 4", y0=0.14)),
            (4, _para("3 6", y0=0.16)),
        ]
        runs = _find_table_runs(blocks)
        assert len(runs) == 1
        in_run = sorted(idx for group in runs[0] for idx, _ in group)
        assert in_run == [0, 1, 2, 3, 4]


def _inline(text, x0, y0, w=0.03, h=0.008):
    return TextLineInline(
        spans=[StyledTextSpan(text=text)],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=x0, y0=y0, x1=x0 + w, y1=y0 + h),
            page_or_screen_index=0,
        ),
    )


class TestRowsFromBlock:
    def test_two_fragments_in_one_bin_keep_both_texts(self):
        from src.analyzers.table.rules import _rows_from_block
        block = ParagraphBlock(
            inlines=[
                _inline("Tj", 0.30, 0.50),
                _inline("-25C", 0.31, 0.50),
                _inline("10", 0.60, 0.50),
                _inline("20", 0.60, 0.52),
            ],
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(x0=0.3, y0=0.5, x1=0.65, y1=0.53),
                page_or_screen_index=0,
            ),
        )
        rows = _rows_from_block(block)
        texts = " ".join(
            s.text for row in rows for cell in row
            for p in cell.content for il in p.inlines for s in il.spans
        )
        assert "Tj" in texts and "-25C" in texts


class TestMergeOrphanRows:
    def test_two_lines_above_a_row_keep_print_order(self):
        from src.analyzers.table.analyzer import _cell_text, _merge_orphan_rows
        grid = [
            [_cell("Label", x0=0.10, y0=0.40), _cell("1", x0=0.30, y0=0.40)],
            [_cell("A", x0=0.20, y0=0.486)],
            [_cell("B", x0=0.20, y0=0.493)],
            [_cell("Row", x0=0.10, y0=0.50), _cell("T", x0=0.20, y0=0.50),
             _cell("2", x0=0.30, y0=0.50)],
        ]
        out = _merge_orphan_rows(grid)
        assert len(out) == 2
        merged = [c for c in out[1] if "T" in _cell_text(c)][0]
        assert _cell_text(merged).split() == ["A", "B", "T"]


class TestMarkCellBorders:
    def test_short_table_keeps_its_column_rules(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _mark_cell_borders

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        x0, x1, y0, y1 = 200.0, 400.0, 300.0, 340.0  # 40pt tall
        for x in (x0, 300.0, x1):
            page.draw_line((x, y0), (x, y1), width=1)
        for y in (y0, y1):
            page.draw_line((x0, y), (x1, y), width=1)
        pw, ph = page.rect.width, page.rect.height

        def cell(cx0, cx1):
            return TableCell(
                content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="x")])])],
                visual_layout=VisualLayout(
                    bounding_box=NormalizedRect(
                        x0=cx0 / pw, y0=(y0 + 5) / ph, x1=cx1 / pw, y1=(y1 - 5) / ph),
                    page_or_screen_index=0,
                ),
            )

        table = TableBlock(
            grid=[[cell(x0 + 5, 295), cell(305, x1 - 5)]], row_count=1, column_count=2,
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(x0=(x0 + 5) / pw, y0=(y0 + 5) / ph,
                                            x1=(x1 - 5) / pw, y1=(y1 - 5) / ph),
                page_or_screen_index=0,
            ),
        )
        _mark_cell_borders(np, pymupdf, page, table)
        assert len((table.metadata or {}).get("column_rule_x", [])) == 1


class TestSplitNumericPair:
    def test_second_token_starts_after_the_gap(self):
        from src.analyzers.table.rules import _split_numeric_pair
        box = NormalizedRect(x0=0.0, y0=0.5, x1=0.11, y1=0.51)  # 11 characters
        parts = _split_numeric_pair("63 00111111", box, None)
        assert [t for t, _, _ in parts] == ["63", "00111111"]
        assert abs(parts[1][1].x0 - 0.03) < 1e-9  # after "63 "
        assert abs(parts[0][1].x1 - 0.02) < 1e-9
        assert abs(parts[1][1].x1 - 0.11) < 1e-9


class TestInferRowspans:
    def test_row_missing_a_middle_column_spans_that_column(self):
        from src.analyzers.table.analyzer import _infer_rowspans
        a, b, c = _cell("a", x0=0.1), _cell("b", x0=0.2), _cell("c", x0=0.3)
        grid = [
            [a, b, c],
            [_cell("d", x0=0.1, y0=0.52), _cell("f", x0=0.3, y0=0.52)],  # no x0=0.2
        ]
        _infer_rowspans(grid)
        assert b.row_span == 2
        assert c.row_span == 1
