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


    def test_label_between_two_rows_spans_them(self):
        from src.analyzers.table.analyzer import _cell_text, _merge_orphan_rows
        grid = [
            [_cell("L", x0=0.10, y0=0.40), _cell("c", x0=0.50, y0=0.40), _cell("1", x0=0.80, y0=0.40)],
            [_cell("c1", x0=0.50, y0=0.50), _cell("2", x0=0.80, y0=0.50)],
            [_cell("Average Temperature", x0=0.10, y0=0.505)],
            [_cell("c2", x0=0.50, y0=0.51), _cell("3", x0=0.80, y0=0.51)],
        ]
        out = _merge_orphan_rows(grid)
        assert len(out) == 3
        label = [c for c in out[1] if _cell_text(c) == "Average Temperature"]
        assert label and label[0].row_span == 2
        assert [_cell_text(c) for c in out[1]][0] == "Average Temperature"

    def test_label_stays_its_own_row_when_its_column_is_taken(self):
        from src.analyzers.table.analyzer import _cell_text, _merge_orphan_rows
        grid = [
            [_cell("Head", x0=0.10, y0=0.40), _cell("c", x0=0.50, y0=0.40), _cell("1", x0=0.80, y0=0.40)],
            [_cell("with line", x0=0.16, y0=0.50), _cell("c1", x0=0.50, y0=0.50), _cell("2", x0=0.80, y0=0.50)],
            [_cell("Quiescent Current Change", x0=0.10, y0=0.506)],
            [_cell("with load", x0=0.16, y0=0.512), _cell("c2", x0=0.50, y0=0.512), _cell("3", x0=0.80, y0=0.512)],
        ]
        out = _merge_orphan_rows(grid)
        texts = [_cell_text(c) for row in out for c in row]
        assert "Quiescent Current Change" in texts
        assert not any(len(row) > 3 for row in out), "label pushed into a row whose column it shares"


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


def _frag(text, x0, y0):
    return (text, NormalizedRect(x0=x0, y0=y0, x1=x0 + 0.03, y1=y0 + 0.008), None)


class TestMergeStrayRows:
    def test_mark_joins_the_nearer_row(self):
        from src.analyzers.table.rules import _merge_stray_rows
        rows = [[_frag("r", 0.1, y), _frag("v", 0.3, y)] for y in (0.40, 0.42, 0.44)]
        dot = [_frag("•", 0.2, 0.451)]  # 0.011 under row 0.44, 0.009 above 0.46
        rows += [dot] + [[_frag("r", 0.1, y), _frag("v", 0.3, y)] for y in (0.46, 0.48)]
        out = _merge_stray_rows(rows)
        assert len(out) == 5
        joined = [r for r in out if any(t == "•" for t, _, _ in r)][0]
        assert min(f[1].y0 for f in joined if f[0] != "•") == 0.46


class TestRecoverPlaceholderMarks:
    def _setup(self):
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        pw, ph = page.rect.width, page.rect.height
        # two columns at x 200 and 300, three rows 20pt apart, cells 14pt tall
        rows_y = (300.0, 320.0, 340.0)

        def cell(text, x, y):
            return TableCell(
                content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])])],
                visual_layout=VisualLayout(
                    bounding_box=NormalizedRect(x0=x / pw, y0=y / ph, x1=(x + 40) / pw, y1=(y + 14) / ph),
                    page_or_screen_index=0,
                ),
            )

        grid = [
            [cell("0", 200, rows_y[0]), cell("32", 300, rows_y[0])],
            [cell("1", 200, rows_y[1])],                       # column 2 empty
            [cell("2", 200, rows_y[2]), cell("34", 300, rows_y[2])],
        ]
        table = TableBlock(
            grid=grid, row_count=3, column_count=2,
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(x0=200 / pw, y0=300 / ph, x1=340 / pw, y1=354 / ph),
                page_or_screen_index=0,
            ),
        )
        return doc, page, table, rows_y

    def test_dot_in_an_empty_cell_is_found_but_the_grid_is_untouched(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _find_placeholder_marks
        doc, page, table, rows_y = self._setup()
        page.draw_circle((315, rows_y[1] + 7), 1.8, color=(0, 0, 0), fill=(0, 0, 0))
        assert _find_placeholder_marks(np, pymupdf, page, table) == 1
        marks = table.metadata["placeholder_marks"]
        assert [m["row"] for m in marks] == [1]
        assert len(table.grid[1]) == 1, "the KRM grid must keep only the text layer's cells"

    def test_non_dots_and_filled_cells_are_left_alone(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _find_placeholder_marks
        doc, page, table, rows_y = self._setup()
        # a thin bar in the empty cell, and a dot in the gap beside an occupied cell
        page.draw_line((315, rows_y[1] + 2), (315, rows_y[1] + 12), width=1)
        page.draw_circle((318, rows_y[0] + 7), 1.8, color=(0, 0, 0), fill=(0, 0, 0))
        assert _find_placeholder_marks(np, pymupdf, page, table) == 0
        assert not (table.metadata or {}).get("placeholder_marks")

    def test_builder_draws_a_found_mark_into_its_cell(self):
        from src.assembler.latex_builder import _cell_text, _grid_with_placeholder_marks
        doc, page, table, rows_y = self._setup()
        pw, ph = page.rect.width, page.rect.height
        table.metadata = {"placeholder_marks": [
            {"row": 1, "bbox": [313 / pw, (rows_y[1] + 5) / ph, 317 / pw, (rows_y[1] + 9) / ph]},
        ]}
        drawn = _grid_with_placeholder_marks(table)
        assert [_cell_text(c) for c in drawn[1]] == ["1", "\u2022"]
        assert len(table.grid[1]) == 1


class TestRuleDrivenRows:
    def test_wrapped_line_count_uses_real_glyph_widths(self):
        from src.assembler.latex_builder import _wrapped_line_count
        text = "15.5 V < V|n < 27 V 5 mA < l0UT < 1 JO A K 15 W"
        # at 5.48pt this sets on one line in the fixture's 123pt column
        assert _wrapped_line_count(text, 123.0, 5.48, False) == 1
        assert _wrapped_line_count(text, 60.0, 5.48, False) >= 2

    def test_rules_are_drawn_only_where_the_source_has_them(self):
        from src.assembler.latex_builder import build_latex
        from src.krm.models import KnowledgeDocument
        ph = 29.7 * 28.3465
        rows = [["Head", "H2"], ["a", "1"], ["b", "2"], ["c", "3"]]
        table = _table(rows, y0=0.30)
        # cells are 0.02 apart (row centres at 0.305, 0.325, ...): measured rules
        # above row 0, under row 0 and under the last row only
        table.metadata = {"rule_y": [0.297, 0.315, 0.3765]}
        doc = KnowledgeDocument(
            title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
        )
        tex = build_latex(doc)
        body = tex[tex.index("\\begin{tabular}"):tex.index("\\end{tabular}")]
        assert body.count("\\hline") == 3


class TestHeaderPrintedPosition:
    def test_snapping_a_header_keeps_where_it_was_printed(self):
        from src.analyzers.table.rules import _snap_row_to_columns
        body = [[_cell("0", x0=0.20), _cell("00000000", x0=0.30)]]
        header = [_cell("Decimal", x0=0.15), _cell("Binary", x0=0.34)]
        snapped = _snap_row_to_columns(header, body)
        assert snapped[1].visual_layout.bounding_box.x0 == 0.30      # binned to its column
        assert snapped[1].metadata["printed_x"][0] == 0.34            # but printed here


class TestRuleWeight:
    def test_the_sources_rule_weight_is_measured(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _mark_cell_borders
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        pw, ph = page.rect.width, page.rect.height
        for x in (200.0, 300.0, 400.0):
            page.draw_line((x, 300), (x, 380), width=1.5)
        for y in (300.0, 340.0, 380.0):
            page.draw_line((200, y), (400, y), width=1.5)
        cells = [
            TableCell(
                content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="x")])])],
                visual_layout=VisualLayout(
                    bounding_box=NormalizedRect(x0=x0 / pw, y0=y0 / ph, x1=(x0 + 40) / pw, y1=(y0 + 12) / ph),
                    page_or_screen_index=0,
                ),
            )
            for x0, y0 in ((230, 314), (330, 314), (230, 354), (330, 354))
        ]
        table = TableBlock(
            grid=[cells[:2], cells[2:]], row_count=2, column_count=2,
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(x0=230 / pw, y0=314 / ph, x1=370 / pw, y1=366 / ph),
                page_or_screen_index=0,
            ),
        )
        _mark_cell_borders(np, pymupdf, page, table)
        assert 1.0 <= table.metadata["rule_width_pt"] <= 2.0


class TestSideBySideCells:
    def test_two_cells_in_one_column_are_both_drawn(self):
        from src.assembler.latex_builder import build_latex
        from src.krm.models import KnowledgeDocument
        table = _table([["Head", "Cond", "Min"], ["Label", "Tj", "1"], ["L2", "X", "2"]], y0=0.30)
        # a second condition printed beside "Tj", in the same column
        extra = _cell("145V<VIN<30V", x0=0.235, y0=0.32)
        table.grid[1].insert(2, extra)
        doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
        tex = build_latex(doc)
        assert "Tj" in tex and "145V" in tex


class TestDisjointRowsInterleave:
    @staticmethod
    def _first_extra(sub_x0):
        import re
        from src.assembler.latex_builder import build_latex
        from src.krm.models import KnowledgeDocument
        # "sub" printed 0.005 of the page (about 4pt) under "Label"
        rows = [[_cell("Label", x0=0.10, y0=0.300), _cell("1", x0=0.40, y0=0.300)],
                [_cell("sub", x0=sub_x0, y0=0.305), _cell("", x0=0.52, y0=0.305)],
                [_cell("Next", x0=0.10, y0=0.325), _cell("2", x0=0.40, y0=0.325)]]
        table = TableBlock(
            grid=rows, row_count=3, column_count=2,
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(x0=0.10, y0=0.300, x1=0.45, y1=0.335),
                page_or_screen_index=0,
            ),
        )
        doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
        extras = re.findall(r"\\tabularnewline\[(-?[0-9.]+)pt\]", build_latex(doc))
        return float(extras[0]) if extras else 0.0

    def test_a_row_clear_of_the_next_may_step_under_a_line_box(self):
        # "sub" beside "Label" in x cannot print over it, so the row may
        # close up to the source step; right under it, it may not.
        assert self._first_extra(sub_x0=0.20) < self._first_extra(sub_x0=0.10)
