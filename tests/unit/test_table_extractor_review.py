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
