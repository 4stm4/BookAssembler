"""A figure of a scanned page: where it stands (diagram.rules.figure_area)
and how its own ink is drawn (latex_builder._scan_ink)."""

from src.analyzers.diagram.rules import figure_area
from src.assembler.latex_builder import _FILL_RECTS, _scan_ink


def test_a_figure_spans_the_band_between_its_caption_and_the_text_across():
    labels = [(0.40, 0.60, 0.45, 0.61), (0.80, 0.70, 0.84, 0.71)]
    area = figure_area(labels, prose=[], band=(0.52, 0.90))
    assert area == (0.0, 0.52, 1.0, 0.90)


def test_a_column_of_text_beside_a_figure_bounds_it():
    # the Intel 3000 manual's block diagram, its left column running on down
    # beside it
    labels = [(0.40, 0.60, 0.45, 0.61), (0.80, 0.70, 0.84, 0.71)]
    left_column = [(0.05, 0.46, 0.31, 0.65), (0.05, 0.64, 0.31, 0.81)]
    text_over = [(0.34, 0.33, 0.60, 0.52)]   # ends where the band begins
    area = figure_area(labels, prose=left_column + text_over, band=(0.52, 0.90))
    assert area == (0.31, 0.52, 1.0, 0.90)


def test_a_figure_s_ink_is_drawn_in_paths_of_a_few_hundred_rectangles():
    # a run on every other row - nothing joins - more runs than one path holds
    runs = [[2 * r, 0, 3] for r in range(2 * _FILL_RECTS + 1)]
    scan = {"box": [0.1, 0.1, 0.2, 0.2], "shape": [4 * _FILL_RECTS + 2, 3], "runs": runs}
    out = _scan_ink(scan, 100.0, 100.0, (0.0, 0.0), "")
    assert out.count("\\fill") == 3
    assert out.count("rectangle") == 2 * _FILL_RECTS + 1
