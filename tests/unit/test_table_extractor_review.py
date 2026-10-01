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
        # "Tj" is boxed to the printed distance from its start to "145V"'s
        # (0.235 - 0.2 of the page), so "145V" starts where it was printed
        assert "\\makebox[20.91pt][l]{" in tex


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


class TestOpenEdgesAndSpanRules:
    @staticmethod
    def _tex(**metadata):
        from src.assembler.latex_builder import build_latex
        from src.krm.models import KnowledgeDocument
        table = _table([["Name", "Head", "Unit"], ["Label", "Tj", "V"], ["L2", "X", "mA"]], y0=0.30)
        for row in table.grid:
            for cell in row:
                cell.border_left = cell.border_right = True
        table.metadata = {"column_rule_x": [0.175, 0.275], **metadata}
        doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
        tex = build_latex(doc)
        return tex, next(l for l in tex.splitlines() if "begin{tabular}" in l)

    def test_a_side_without_a_frame_rule_is_not_padded(self):
        _, spec = self._tex()
        assert spec.startswith("\\begin{tabular}{@{}") and spec.endswith("@{}}")

    def test_a_framed_side_keeps_its_rule(self):
        _, spec = self._tex(table_rule_x0=0.09, table_rule_x1=0.36)
        assert spec.startswith("\\begin{tabular}{|") and spec.endswith("|}")

    def test_a_multicolumn_past_the_first_does_not_repeat_the_left_rule(self):
        # "Head" is centred in its column, so it is set as a \multicolumn
        tex, _ = self._tex()
        assert "\\multicolumn{1}{c|}" in tex
        assert "\\multicolumn{1}{|" not in tex


class TestPartialRules:
    def test_a_rule_the_source_stops_short_is_drawn_short(self):
        full, part = [0.10, 0.40], [0.20, 0.40]
        tex, _ = TestOpenEdgesAndSpanRules._tex(
            rule_y=[0.295, 0.315, 0.335, 0.355],
            rule_x_extent=[full, part, full, full],
        )
        body = tex[tex.index("begin{tabular}"):tex.index("end{tabular}")]
        assert body.count("\\hline") == 3
        assert body.count("\\noalign{\\hbox to 0pt{\\hskip") == 1

    def test_the_extent_of_a_rule_bridges_scan_dropout(self):
        import numpy as np
        from src.analyzers.table.rules import _rule_extent
        ink = np.zeros((6, 300), dtype=bool)
        ink[2:4, 60:280] = True
        ink[2:4, 150:153] = False   # 1pt of dropout
        ink[2:4, 10:40] = True      # a separate stroke 20pt to the left
        assert _rule_extent(np, ink, (2, 4)) == (60, 280)


def _styled(cell, size_pt=8.0):
    from src.krm.models import StyleDescriptor
    cell.visual_layout.style = StyleDescriptor(font_size_pt=size_pt)
    return cell


def _ruled_tex(rows, x1=0.40):
    """build_latex of a three-column table ruled at 0.175 and 0.275, no frame."""
    from src.assembler.latex_builder import build_latex
    from src.krm.models import KnowledgeDocument
    grid = [[c if c.visual_layout.style else _styled(c) for c in row] for row in rows]
    table = TableBlock(
        grid=grid, row_count=len(grid), column_count=3,
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=0.10, y0=0.30, x1=x1, y1=0.30 + 0.02 * len(grid)),
            page_or_screen_index=0,
        ),
    )
    for row in grid:
        for cell in row:
            cell.border_left = cell.border_right = True
    table.metadata = {"column_rule_x": [0.175, 0.275]}
    doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
    return build_latex(doc)


class TestPrintedHeight:
    @staticmethod
    def _rows(label_drop):
        return [
            [_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("Unit", x0=0.33, y0=0.30)],
            [_cell("Label", x0=0.10, y0=0.32 + label_drop), _cell("Tj", x0=0.20, y0=0.32), _cell("V", x0=0.33, y0=0.32)],
            [_cell("L2", x0=0.10, y0=0.34), _cell("X", x0=0.20, y0=0.34), _cell("mA", x0=0.33, y0=0.34)],
        ]

    def test_a_label_printed_on_its_block_is_lowered_to_it(self):
        # 0.006 of the page is 5pt, half a 9.6pt line
        import re
        drops = re.findall(r"\\raisebox\{-([0-9.]+)pt\}\[0pt\]\[0pt\]\{", _ruled_tex(self._rows(0.006)))
        assert len(drops) == 1 and 4.5 < float(drops[0]) < 5.5

    def test_jitter_within_a_line_is_left_alone(self):
        assert "\\raisebox" not in _ruled_tex(self._rows(0.001))


class TestNarrowCellsFitTheirColumn:
    def test_a_cell_wider_than_its_column_does_not_widen_it(self):
        # "mV/VOUT" is printed 0.05 of the page wide from right against the
        # last rule, in a column 0.055 wide with no frame on its right
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("mV/VOUT", x0=0.28, y0=0.30)],
                [_cell("L", x0=0.10, y0=0.32), _cell("X", x0=0.20, y0=0.32), _cell("V", x0=0.32, y0=0.32)]]
        tex = _ruled_tex(rows, x1=0.33)
        spec = next(l for l in tex.splitlines() if "begin{tabular}" in l)
        # 0.055 * 21cm less one padding and half a rule, not its 1.05cm text
        assert spec.endswith("p{1.01cm}@{}}")
        assert "[r]{\\latinfont \\fontsize{8.00}{9.60}\\selectfont mV/VOUT" in tex


class TestStackedLines:
    @staticmethod
    def _tex(cond_height):
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("Label", x0=0.10, y0=0.32), _cell("15 V\n5 mA\nP", x0=0.20, y0=0.32), _cell("V", x0=0.33, y0=0.32)]]
        box = rows[1][1].visual_layout.bounding_box
        rows[1][1].visual_layout.bounding_box = NormalizedRect(x0=box.x0, y0=box.y0, x1=box.x1, y1=box.y0 + cond_height)
        return _ruled_tex(rows)

    def test_lines_printed_one_under_another_stay_so(self):
        # 0.03 of the page is 25pt, three 9.6pt lines; \\ would end the row
        tex = self._tex(0.03)
        assert "15 V\\newline 5 mA\\newline P" in tex
        assert "15 V\\\\" not in tex

    def test_lines_printed_as_one_are_joined(self):
        assert "15 V 5 mA P" in self._tex(0.01)



class TestRowSpannedPositions:
    def test_a_row_under_a_multirow_keeps_all_its_columns(self):
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("Label", x0=0.10, y0=0.32), _cell("aa", x0=0.20, y0=0.32), _cell("1", x0=0.33, y0=0.32)],
                [_cell("bb", x0=0.20, y0=0.34), _cell("2", x0=0.33, y0=0.34)]]
        rows[1][0].row_span = 2
        tex = _ruled_tex(rows)
        last = next(l for l in tex.splitlines() if " bb" in l)
        # the spanned first column is still there, empty
        assert last.count("&") == 2 and last.lstrip().startswith("&")


class TestSizeNoise:
    def test_a_size_the_line_box_contradicts_is_the_tables(self):
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("Label", x0=0.10, y0=0.32), _cell("small", x0=0.20, y0=0.32), _cell("1", x0=0.33, y0=0.32)]]
        # read as 3.12pt, in an 8.4pt box like its 8pt neighbours'
        _styled(rows[1][1], 3.12)
        tex = _ruled_tex(rows)
        assert "\\fontsize{3.12}" not in tex
        assert "\\fontsize{8.00}{9.60}\\selectfont small" in tex


class TestTextUnderRules:
    def test_text_printed_close_under_a_rule_is_lifted_to_it(self):
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("Label", x0=0.10, y0=0.32), _cell("aa", x0=0.20, y0=0.32), _cell("1", x0=0.33, y0=0.32)]]
        from src.assembler.latex_builder import build_latex
        from src.krm.models import KnowledgeDocument
        grid = [[_styled(c) for c in row] for row in rows]
        table = TableBlock(
            grid=grid, row_count=2, column_count=3,
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(x0=0.10, y0=0.30, x1=0.40, y1=0.34), page_or_screen_index=0,
            ),
        )
        for row in grid:
            for cell in row:
                cell.border_left = cell.border_right = True
        # glyphs 0.5..6.0pt under the middle rule, far closer than LaTeX's strut sets them
        table.metadata = {
            "column_rule_x": [0.175, 0.275], "rule_y": [0.298, 0.3185, 0.3385],
            "text_band_pt": [[0.5, 6.0], [0.5, 6.0], None],
        }
        doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
        assert "\\noalign{\\vskip -" in build_latex(doc)


class TestPlacementByBoxes:
    def test_a_value_printed_past_its_column_edge_overhangs_it(self):
        # right-set units ending at 0.37 of the page, one printed 5pt further
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("Unit", x0=0.32, y0=0.30)],
                [_cell("L1", x0=0.10, y0=0.32), _cell("a", x0=0.20, y0=0.32), _cell("mV", x0=0.32, y0=0.32)],
                [_cell("L2", x0=0.10, y0=0.34), _cell("b", x0=0.20, y0=0.34), _cell("mA", x0=0.32, y0=0.34)],
                [_cell("L3", x0=0.10, y0=0.36), _cell("c", x0=0.20, y0=0.36), _cell("uV/VOUT", x0=0.3284, y0=0.36)]]
        tex = _ruled_tex(rows)
        assert "uV/VOUT\\kern-" in tex

    def test_a_box_shared_out_by_character_count_is_not_placed_by(self):
        from src.analyzers.table.rules import _make_cell, _split_numeric_pair
        parts = _split_numeric_pair("63 00111111", NormalizedRect(x0=0.2, y0=0.3, x1=0.4, y1=0.31), None)
        cells = [_make_cell(t, b, s, 0) for t, b, s in parts]
        assert all(c.metadata.get("x_estimated") for c in cells)
        assert not _make_cell("63", NormalizedRect(x0=0.2, y0=0.3, x1=0.25, y1=0.31), None, 0).metadata.get("x_estimated")


class TestFoldLabelRows:
    @staticmethod
    def _table(rules):
        from src.analyzers.table.rules import _build_span_map
        rows = [[_cell("with line", x0=0.20, y0=0.300), _cell("0.8", x0=0.33, y0=0.300)],
                [_cell("Quiescent", x0=0.08, y0=0.305)],
                [_cell("with load", x0=0.20, y0=0.312), _cell("0.5", x0=0.33, y0=0.312)]]
        rows[1][0].visual_layout = VisualLayout(
            bounding_box=NormalizedRect(x0=0.08, y0=0.305, x1=0.18, y1=0.312), page_or_screen_index=0)
        table = TableBlock(grid=rows, row_count=3, column_count=2,
                           visual_layout=VisualLayout(bounding_box=NormalizedRect(x0=0.08, y0=0.30, x1=0.38, y1=0.32),
                                                      page_or_screen_index=0))
        table.span_map = _build_span_map(rows)
        table.metadata = {"rule_y": rules}
        return table

    def test_a_label_beside_its_sub_rows_joins_the_one_above(self):
        from src.analyzers.table.rules import _fold_label_rows, _cell_text_of
        table = self._table([0.298, 0.3115, 0.323])
        _fold_label_rows(table)
        assert table.row_count == 2
        assert [_cell_text_of(c) for c in table.grid[0]] == ["Quiescent", "with line", "0.8"]

    def test_a_rule_between_keeps_it_a_row(self):
        from src.analyzers.table.rules import _fold_label_rows
        table = self._table([0.298, 0.307, 0.3115, 0.323])
        _fold_label_rows(table)
        assert table.row_count == 3


class TestUnreadTextBand:
    def test_a_row_whose_text_could_not_be_read_sits_as_the_others(self):
        from src.assembler.latex_builder import build_latex
        from src.krm.models import KnowledgeDocument
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("L1", x0=0.10, y0=0.32), _cell("aa", x0=0.20, y0=0.32), _cell("1", x0=0.33, y0=0.32)],
                [_cell("L2", x0=0.10, y0=0.34), _cell("bb", x0=0.20, y0=0.34), _cell("2", x0=0.33, y0=0.34)]]
        grid = [[_styled(c) for c in row] for row in rows]
        table = TableBlock(grid=grid, row_count=3, column_count=3, visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=0.10, y0=0.30, x1=0.40, y1=0.35), page_or_screen_index=0))
        for row in grid:
            for cell in row:
                cell.border_left = cell.border_right = True
        # the text under the third rule ran into its fringe and was not read
        table.metadata = {
            "column_rule_x": [0.175, 0.275], "rule_y": [0.298, 0.3185, 0.3385, 0.3585],
            "text_band_pt": [[0.5, 6.0], [0.5, 6.0], None, None],
        }
        doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
        # header and first row lifted by their bands, the second by the usual lift
        assert build_latex(doc).count("\\noalign{\\vskip -") == 3


class TestSplitCellsAtRules:
    def test_words_on_both_sides_of_a_rule_become_two_cells(self):
        import pymupdf
        from src.analyzers.table.rules import _cell_text_of, _split_cells_at_rules
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((120, 300), "Output Voltage", fontsize=8)
        page.insert_text((230, 300), "IOUT", fontsize=8)
        pw, ph = page.rect.width, page.rect.height
        words = page.get_text("words")
        x0, x1 = min(w[0] for w in words), max(w[2] for w in words)
        y0, y1 = min(w[1] for w in words), max(w[3] for w in words)
        cell = TableCell(
            content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Output Voltage IOUT")])])],
            visual_layout=VisualLayout(bounding_box=NormalizedRect(x0=x0 / pw, y0=y0 / ph, x1=x1 / pw, y1=y1 / ph),
                                       page_or_screen_index=0),
        )
        table = TableBlock(grid=[[cell]], row_count=1, column_count=2,
                           visual_layout=VisualLayout(bounding_box=cell.visual_layout.bounding_box, page_or_screen_index=0))
        table.metadata = {"column_rule_x": [220 / pw]}
        _split_cells_at_rules(page, table)
        assert [_cell_text_of(c) for c in table.grid[0]] == ["Output Voltage", "IOUT"]
        assert table.grid[0][1].visual_layout.bounding_box.x0 * pw >= 229


class TestOneLineMultirow:
    def test_a_label_printed_on_one_line_spans_its_rows_unwrapped(self):
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("Label", x0=0.10, y0=0.32), _cell("aa", x0=0.20, y0=0.32), _cell("1", x0=0.33, y0=0.32)],
                [_cell("bb", x0=0.20, y0=0.34), _cell("2", x0=0.33, y0=0.34)]]
        rows[1][0].row_span = 2
        assert "\\multirow{2}{*}{" in _ruled_tex(rows)


class TestSubColumnRules:
    def test_a_rule_between_two_horizontals_only_is_found(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _mark_cell_borders
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        pw, ph = page.rect.width, page.rect.height
        for x in (200.0, 300.0, 400.0):
            page.draw_line((x, 300), (x, 420), width=1.5)
        for y in (300.0, 340.0, 380.0, 420.0):
            page.draw_line((200, y), (400, y), width=1.5)
        page.draw_line((250, 340), (250, 380), width=1.5)   # the middle band only
        cells = [
            TableCell(
                content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="x")])])],
                visual_layout=VisualLayout(
                    bounding_box=NormalizedRect(x0=x0 / pw, y0=y0 / ph, x1=(x0 + 20) / pw, y1=(y0 + 12) / ph),
                    page_or_screen_index=0,
                ),
            )
            for y0 in (314, 354, 394) for x0 in (210, 330)
        ]
        table = TableBlock(
            grid=[cells[0:2], cells[2:4], cells[4:6]], row_count=3, column_count=2,
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(x0=210 / pw, y0=314 / ph, x1=350 / pw, y1=406 / ph),
                page_or_screen_index=0,
            ),
        )
        _mark_cell_borders(np, pymupdf, page, table)
        subs = table.metadata["sub_rule"]
        assert len(subs) == 1
        x, y0, y1 = subs[0]
        assert abs(x * pw - 250) < 1 and abs(y0 * ph - 340) < 1 and abs(y1 * ph - 380) < 1

    def test_it_is_drawn_from_rule_to_rule(self):
        from src.assembler.latex_builder import build_latex
        from src.krm.models import KnowledgeDocument
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("L1", x0=0.10, y0=0.32), _cell("aa", x0=0.20, y0=0.32), _cell("1", x0=0.33, y0=0.32)],
                [_cell("L2", x0=0.10, y0=0.34), _cell("bb", x0=0.20, y0=0.34), _cell("2", x0=0.33, y0=0.34)]]
        grid = [[_styled(c) for c in row] for row in rows]
        table = TableBlock(grid=grid, row_count=3, column_count=3, visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=0.10, y0=0.30, x1=0.40, y1=0.35), page_or_screen_index=0))
        for row in grid:
            for cell in row:
                cell.border_left = cell.border_right = True
        table.metadata = {"column_rule_x": [0.175, 0.275], "rule_y": [0.298, 0.3185, 0.3385, 0.3585],
                          "sub_rule": [[0.22, 0.3185, 0.3585]]}
        doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
        tex = build_latex(doc)
        # hung from the second rule, as deep as the 0.04 of the page to the last
        assert tex.count("height 0pt depth") == 1
        # (0.3585 - 0.3185) x 845.04pt, less the 0.4pt rule weight
        assert "depth 33.40pt" in tex


class TestRuleWeightEach:
    def test_each_rule_is_drawn_at_its_own_weight(self):
        from src.assembler.latex_builder import build_latex
        from src.krm.models import KnowledgeDocument
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("L1", x0=0.10, y0=0.32), _cell("aa", x0=0.20, y0=0.32), _cell("1", x0=0.33, y0=0.32)]]
        grid = [[_styled(c) for c in row] for row in rows]
        table = TableBlock(grid=grid, row_count=2, column_count=3, visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=0.10, y0=0.30, x1=0.40, y1=0.33), page_or_screen_index=0))
        for row in grid:
            for cell in row:
                cell.border_left = cell.border_right = True
        table.metadata = {"column_rule_x": [0.175, 0.275], "rule_y": [0.298, 0.3185, 0.3385],
                          "rule_weight_pt": [1.0, 1.5, 2.0]}
        doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
        tex = build_latex(doc)
        for pt in (1.0, 1.5, 2.0):
            assert f"\\hrule height {pt * 72.27 / 72:.2f}pt" in tex


def _lines_block(lines):
    """A ParagraphBlock of (text, x0, y0, x1) lines in points on an A4 page,
    each line carrying its own box as PdfSourceAdapter gives it."""
    pw, ph = 595.0, 842.0
    inlines = []
    for text, x0, y0, x1 in lines:
        inline = TextLineInline(spans=[StyledTextSpan(text=text)])
        inline.visual_layout = VisualLayout(
            bounding_box=NormalizedRect(x0=x0 / pw, y0=y0 / ph, x1=x1 / pw, y1=(y0 + 8) / ph),
            page_or_screen_index=0,
        )
        inlines.append(inline)
    return ParagraphBlock(
        inlines=inlines,
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(
                x0=min(l[1] for l in lines) / pw, y0=min(l[2] for l in lines) / ph,
                x1=max(l[3] for l in lines) / pw, y1=(max(l[2] for l in lines) + 8) / ph,
            ),
            page_or_screen_index=0,
        ),
    )


class TestFramedRows:
    def _setup(self):
        import pymupdf
        from src.analyzers.table.rules import _table_from_lines
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        for y in (100.0, 120.0, 260.0):
            page.draw_line((100, y), (500, y), width=1.0)
        header = _lines_block([("SYMBOL", 110, 108, 150), ("MIN", 300, 108, 320), ("UNIT", 400, 108, 430)])
        body = _lines_block([(f"V{k}", 110, 140 + 16 * k, 125) for k in range(4)]
                            + [(f"{k}.0", 300, 140 + 16 * k, 315) for k in range(4)]
                            + [("V", 400, 140 + 16 * k, 408) for k in range(4)])
        tail = _lines_block([("IOS", 110, 220, 130), ("-15", 300, 220, 315), ("mA", 400, 220, 415)])
        prose = _lines_block([("A note printed under the table", 110, 280, 300)])
        table = _table_from_lines(body)
        container = ContainerUnit(title="p", children=[header, table, tail, prose])
        return page, container, table, header, tail, prose

    def test_rows_inside_the_frame_rules_join_the_table(self):
        import numpy as np
        import pymupdf
        page, container, table, header, tail, prose = self._setup()
        TableDetectorAnalyzer()._absorb_into(container, table, np, pymupdf, page)
        assert header.is_tombstoned and tail.is_tombstoned
        assert not prose.is_tombstoned
        texts = [c.content[0].inlines[0].spans[0].text for c in table.grid[0]]
        assert texts == ["SYMBOL", "MIN", "UNIT"]
        assert table.grid[-1][0].content[0].inlines[0].spans[0].text == "IOS"

    def test_a_single_block_tables_cells_know_their_block(self):
        _, _, table, _, _, _ = self._setup()
        assert all(c.metadata.get("source_block_id") for row in table.grid for c in row)

    def test_a_pale_rule_is_read_across_its_whole_length(self):
        import numpy as np
        from src.analyzers.table.rules import _rule_extent
        ink = np.zeros((4, 300), dtype=bool)
        ink[1, 20:280:2] = True      # one row inked here,
        ink[2, 21:280:2] = True      # the other there
        assert _rule_extent(np, ink, (1, 3)) == (20, 280)


class TestGriddedFrame:
    def test_a_ruled_grid_takes_its_prose_cells_and_fragments(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _table_from_lines
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        for y in (100.0, 120.0, 200.0, 280.0):
            page.draw_line((100, y), (500, y), width=1.0)
        for x in (100.0, 200.0, 500.0):
            page.draw_line((x, 100), (x, 280), width=1.0)
        header = _lines_block([("Symbol", 110, 108, 150), ("Name and Function", 210, 108, 300)])
        body = _lines_block([(f"S{k}", 110, 130 + 16 * k, 125) for k in range(4)]
                            + [(f"value {k}", 210, 130 + 16 * k, 260) for k in range(4)])
        prose = _lines_block([("A long description of the pin and what it does in every mode " * 3, 210, 210, 495)])
        table = _table_from_lines(body)
        rest = _table_from_lines(_lines_block([(f"T{k}", 110, 230 + 12 * k, 125) for k in range(3)]
                                              + [(f"more {k}", 210, 230 + 12 * k, 260) for k in range(3)]))
        container = ContainerUnit(title="p", children=[header, table, prose, rest])
        TableDetectorAnalyzer()._absorb_into(container, table, np, pymupdf, page)
        assert header.is_tombstoned and prose.is_tombstoned and rest.is_tombstoned
        texts = [c.content[0].inlines[0].spans[0].text for row in table.grid for c in row]
        assert texts[0] == "Symbol" and "T2" in texts and any(t.startswith("A long") for t in texts)


class TestColumnsByRules:
    def test_a_cell_goes_to_the_band_its_centre_is_in(self):
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Type", x0=0.22, y0=0.30), _cell("Function", x0=0.36, y0=0.30)],
                [_cell("L1", x0=0.10, y0=0.32), _cell("O", x0=0.22, y0=0.32), _cell("prose", x0=0.28, y0=0.32)]]
        tex = _ruled_tex(rows, x1=0.42)
        line = next(l for l in tex.splitlines() if "prose" in l)
        # nearer the Type heading's x0 than the centred Function heading's,
        # but between the second rule and the table's edge
        assert "prose" in line.split(" & ")[2]



class TestRegridRuledBands:
    def test_a_paragraph_band_becomes_one_row(self):
        import pymupdf
        from src.analyzers.table.rules import _cell_text_of, _regrid_ruled_bands
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        pw, ph = page.rect.width, page.rect.height
        page.insert_text((110, 312), "ALE", fontsize=8)
        page.insert_text((210, 312), "first line of the function", fontsize=8)
        page.insert_text((210, 324), "and its continuation", fontsize=8)
        page.insert_text((110, 352), "HOLD", fontsize=8)
        page.insert_text((210, 352), "next row", fontsize=8)
        words = page.get_text("words")

        def cell(*texts):
            ws = [w for w in words if w[4] in " ".join(texts).split()]
            return TableCell(
                content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=" ".join(texts))])])],
                visual_layout=VisualLayout(bounding_box=NormalizedRect(
                    x0=min(w[0] for w in ws) / pw, y0=min(w[1] for w in ws) / ph,
                    x1=max(w[2] for w in ws) / pw, y1=max(w[3] for w in ws) / ph), page_or_screen_index=0),
            )
        grid = [[cell("ALE"), cell("first line of the function")], [cell("and its continuation")],
                [cell("HOLD"), cell("next row")]]
        table = TableBlock(grid=grid, row_count=3, column_count=2, visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=100 / pw, y0=300 / ph, x1=400 / pw, y1=360 / ph), page_or_screen_index=0))
        table.metadata = {"column_rule_x": [200 / pw], "rule_y": [300 / ph, 335 / ph, 360 / ph]}
        _regrid_ruled_bands(page, table)
        assert table.row_count == 2
        assert _cell_text_of(table.grid[0][1]) == "first line of the function\nand its continuation"
        assert _cell_text_of(table.grid[1][0]) == "HOLD"

    def test_a_band_of_full_rows_is_left_alone(self):
        import pymupdf
        from src.analyzers.table.rules import _regrid_ruled_bands
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        pw, ph = page.rect.width, page.rect.height
        for k in range(3):
            page.insert_text((110, 312 + 12 * k), f"{k}", fontsize=8)
            page.insert_text((210, 312 + 12 * k), f"0000000{k}", fontsize=8)
        table = TableBlock(grid=[[_cell("x")]], row_count=1, column_count=2, visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=100 / pw, y0=300 / ph, x1=400 / pw, y1=350 / ph), page_or_screen_index=0))
        table.metadata = {"column_rule_x": [200 / pw], "rule_y": [300 / ph, 350 / ph]}
        _regrid_ruled_bands(page, table)
        assert table.row_count == 1 and table.grid[0][0].content[0].inlines[0].spans[0].text == "x"


class TestStackedPitch:
    def test_stacked_lines_take_their_printed_pitch(self):
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("Label", x0=0.10, y0=0.32), _cell("15 V\n5 mA\nP", x0=0.20, y0=0.32), _cell("V", x0=0.33, y0=0.32)]]
        box = rows[1][1].visual_layout.bounding_box
        rows[1][1].visual_layout.bounding_box = NormalizedRect(x0=box.x0, y0=box.y0, x1=box.x1, y1=box.y0 + 0.03)
        tex = _ruled_tex(rows)
        # three lines in a 0.03 box over a 0.01 line: (0.02 x 845.04pt) / 2
        assert "\\fontsize{8.00}{8.45}\\selectfont \\lineskiplimit" in tex

    def test_lines_are_the_printed_ones_and_spans_are_reset(self):
        import pymupdf
        from src.analyzers.table.rules import _cell_text_of, _regrid_ruled_bands
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        pw, ph = page.rect.width, page.rect.height
        page.insert_text((110, 312), "S0", fontsize=8)
        page.insert_text((210, 312), "MACHINE CYCLE STATUS:", fontsize=8)
        page.insert_text((215, 324), "IO/M", fontsize=8)     # each inserted apart:
        page.insert_text((260, 324), "Status", fontsize=8)   # a block of its own
        heading = _cell("Name", x0=210 / pw, y0=285 / ph)
        heading.row_span = 2
        table = TableBlock(grid=[[heading], [_cell("S0", x0=110 / pw, y0=305 / ph)]], row_count=2, column_count=2,
                           visual_layout=VisualLayout(bounding_box=NormalizedRect(
                               x0=100 / pw, y0=280 / ph, x1=400 / pw, y1=335 / ph), page_or_screen_index=0))
        table.metadata = {"column_rule_x": [200 / pw], "rule_y": [295 / ph, 335 / ph]}
        _regrid_ruled_bands(page, table)
        assert _cell_text_of(table.grid[-1][1]) == "MACHINE CYCLE STATUS:\nIO/M Status"
        assert all(c.row_span == 1 for row in table.grid for c in row)


class TestPositionedLines:
    def test_runs_start_where_they_were_printed(self):
        from src.assembler.latex_builder import _A4_WIDTH_PT, _positioned_lines
        cell = _cell("IO/M Status\n0 Memory write", x0=0.30, y0=0.40)
        cell.metadata["line_segments"] = [[[0.30, "IO/M"], [0.36, "Status"]], [[0.31, "0"], [0.36, "Memory write"]]]
        out = _positioned_lines(cell, "IO/M Status\n0 Memory write")
        first, second = out.split("\\newline ")
        assert first == f"\\makebox[{0.06 * _A4_WIDTH_PT:.2f}pt][l]{{IO/M}}Status"
        assert second.startswith(f"\\rule{{{0.01 * _A4_WIDTH_PT:.2f}pt}}{{0pt}}")

    def test_a_justified_word_space_is_not_a_column(self):
        from src.analyzers.table.rules import _runs
        # words 10pt tall: a 7pt stretched space stays, a 14pt gap splits
        line = [(100, 0, 130, 10, "the"), (137, 0, 160, 10, "bus"), (174, 0, 200, 10, "Status")]
        assert [[w[4] for w in r] for r in _runs(line)] == [["the", "bus"], ["Status"]]


class TestWordBold:
    def test_bold_words_are_told_from_regular_ones(self):
        import pymupdf
        from src.analyzers.table.rules import _bold_words
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((100, 300), "ADDRESS BUS:", fontsize=10, fontname="hebo")
        page.insert_text((180, 300), "The most significant bits of memory address", fontsize=10, fontname="helv")
        words = page.get_text("words")
        bold = _bold_words(page, words)
        assert [w[4] for k, w in enumerate(words) if bold.get(k)] == ["ADDRESS", "BUS:"]

    def test_a_lone_word_takes_its_neighbours_weight(self):
        from src.analyzers.table.rules import _smoothed
        # "ADDRESS LATCH ENABLE: it is set to guarantee": LATCH missed, set misread
        flags = [True, False, True, False, False, True, False, False]
        assert _smoothed(flags) == [True, True, True, False, False, False, False, False]

    def test_only_the_bold_words_are_set_bold(self):
        from src.krm.models import StyleDescriptor
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("L1", x0=0.10, y0=0.32), _cell("ADDRESS BUS: the bus", x0=0.20, y0=0.32), _cell("1", x0=0.33, y0=0.32)]]
        rows[1][1].visual_layout.style = StyleDescriptor(font_size_pt=8.0, is_bold=True)
        rows[1][1].metadata["line_bold"] = [[True, True, False, False]]
        tex = _ruled_tex(rows)
        assert "\\textbf{ADDRESS BUS:} the bus" in tex
        line = next(l for l in tex.splitlines() if "ADDRESS" in l)
        assert "\\bfseries \\textbf" not in line and "\\selectfont \\bfseries ADDRESS" not in line


class TestDotLeaders:
    @staticmethod
    def _row(page, texts):
        pw, ph = page.rect.width, page.rect.height
        words = page.get_text("words")
        cells = []
        for t in texts:
            ws = [w for w in words if w[4] in t.split()]
            cells.append(TableCell(
                content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text=t)])])],
                visual_layout=VisualLayout(bounding_box=NormalizedRect(
                    x0=min(w[0] for w in ws) / pw, y0=min(w[1] for w in ws) / ph,
                    x1=max(w[2] for w in ws) / pw, y1=max(w[3] for w in ws) / ph), page_or_screen_index=0),
            ))
        return cells

    def test_a_leader_goes_and_the_page_number_stays(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _cell_text_of, _drop_leaders
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((100, 300), "CLARY CORP", fontsize=10)
        page.insert_text((180, 300), ". . . . . . . . . . . .", fontsize=10)
        page.insert_text((330, 300), "37", fontsize=10)
        row = self._row(page, ["CLARY CORP", ". . . . . . . . . . . .", "37"])
        table = TableBlock(grid=[row], row_count=1, column_count=3, visual_layout=row[0].visual_layout)
        _drop_leaders(np, pymupdf, page, table)
        assert [_cell_text_of(c) for c in table.grid[0]] == ["CLARY CORP", "37"]
        assert table.grid[0][0].metadata.get("leader_after")

    def test_a_lone_placeholder_mark_is_not_a_leader(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _drop_leaders
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((100, 300), "33", fontsize=10)
        page.insert_text((200, 300), ".", fontsize=10)
        page.insert_text((300, 300), "00100001", fontsize=10)
        row = self._row(page, ["33", ".", "00100001"])
        table = TableBlock(grid=[row], row_count=1, column_count=3, visual_layout=row[0].visual_layout)
        assert _drop_leaders(np, pymupdf, page, table) == 0 and len(table.grid[0]) == 3

    def test_the_builder_runs_the_leader_on(self):
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("Cond", x0=0.20, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("CLARY CORP", x0=0.10, y0=0.32), _cell("x", x0=0.20, y0=0.32), _cell("37", x0=0.33, y0=0.32)]]
        rows[1][0].metadata["leader_after"] = True
        assert "CLARY CORP\\dotfill" in _ruled_tex(rows)

    def test_dots_the_ocr_did_not_read_make_a_leader_not_placeholders(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _find_placeholder_marks
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        rows = []
        for k, (name, num) in enumerate((("CLARY CORP", "37"), ("DATA GENERAL", "7"), ("ELGAR INC", "23"))):
            y = 300 + 20 * k
            page.insert_text((100, y), name, fontsize=10)
            page.insert_text((330, y), num, fontsize=10)
            for x in range(190, 320, 9):                    # a leader OCR never read
                page.draw_circle((x, y - 3), 1.8, color=(0, 0, 0), fill=(0, 0, 0))
            rows.append(self._row(page, [name, num]))
        table = TableBlock(grid=rows, row_count=3, column_count=2, visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=100 / 595, y0=290 / 842, x1=345 / 595, y1=345 / 842),
            page_or_screen_index=0))
        _find_placeholder_marks(np, pymupdf, page, table)
        assert not (table.metadata or {}).get("placeholder_marks")
        assert all(row[0].metadata.get("leader_after") for row in table.grid)

    def test_in_a_leader_row_a_stray_dot_goes_and_the_last_word_stays(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _cell_text_of, _drop_leaders
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((100, 300), "BOWERS CORP", fontsize=10)
        page.insert_text((200, 300), ".", fontsize=10)
        page.insert_text((330, 300), "48", fontsize=10)
        row = self._row(page, ["BOWERS CORP", ".", "48"])
        row[0].metadata["leader_after"] = True                  # its leader is known
        table = TableBlock(grid=[row], row_count=1, column_count=3, visual_layout=row[0].visual_layout)
        _drop_leaders(np, pymupdf, page, table)
        assert [_cell_text_of(c) for c in table.grid[0]] == ["BOWERS CORP", "48"]


class TestColumnSupport:
    def test_a_stray_x0_is_not_a_column(self):
        from src.assembler.latex_builder import _column_bins
        grid = [[_cell("index to advertisers", x0=0.10, y0=0.20)]]
        for k in range(8):
            grid.append([_cell(f"NAME {k}", x0=0.10, y0=0.25 + 0.02 * k), _cell(f"{k}", x0=0.70, y0=0.25 + 0.02 * k)])
        grid[3].insert(1, _cell("2...", x0=0.40, y0=0.29))       # an OCR'd leader's leftover
        assert _column_bins(grid) == [0.10, 0.70]


class TestTableFill:
    def test_the_colour_a_table_is_printed_on_is_recorded_and_set(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _mark_fill
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.draw_rect(pymupdf.Rect(90, 280, 400, 360), color=None, fill=(240 / 255, 198 / 255, 167 / 255))
        page.insert_text((100, 300), "CLARY CORP", fontsize=10)
        table = TableBlock(grid=[[_cell("CLARY CORP")]], row_count=1, column_count=1, visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=95 / 595, y0=285 / 842, x1=395 / 595, y1=355 / 842), page_or_screen_index=0))
        rgb = _mark_fill(np, pymupdf, page, table)
        assert rgb is not None and all(abs(a - b) <= 2 for a, b in zip(rgb, (240, 198, 167)))

    def test_paper_is_not_a_fill(self):
        import numpy as np
        import pymupdf
        from src.analyzers.table.rules import _mark_fill
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((100, 300), "CLARY CORP", fontsize=10)
        table = TableBlock(grid=[[_cell("CLARY CORP")]], row_count=1, column_count=1, visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=95 / 595, y0=285 / 842, x1=395 / 595, y1=355 / 842), page_or_screen_index=0))
        assert _mark_fill(np, pymupdf, page, table) is None and "fill_rgb" not in (table.metadata or {})

    def test_the_builder_sets_the_table_on_it(self):
        from src.assembler.latex_builder import build_latex
        from src.krm.models import KnowledgeDocument
        rows = [[_cell("Name", x0=0.10, y0=0.30), _cell("V", x0=0.33, y0=0.30)],
                [_cell("CLARY CORP", x0=0.10, y0=0.32), _cell("37", x0=0.33, y0=0.32)]]
        table = TableBlock(grid=rows, row_count=2, column_count=2, visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0=0.10, y0=0.30, x1=0.40, y1=0.33), page_or_screen_index=0))
        table.metadata = {"fill_rgb": [240, 198, 167]}
        doc = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])])
        assert "\\colorbox[RGB]{240,198,167}{\\begin{tabular}" in build_latex(doc)
