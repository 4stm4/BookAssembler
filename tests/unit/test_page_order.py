"""page_order.reading_order - a scanned page's blocks in the order it is read.

Boxes are page-normalised (x0, y0, x1, y1); the gutter is the narrowest
gap between two columns, here 0.02 of the page's width.
"""

from src.analyzers.page_order.rules import reading_order

GUTTER = 0.02


def _order(boxes):
    return reading_order(boxes, GUTTER)


def test_columns_are_read_one_after_another():
    # two columns of three paragraphs each, listed row by row
    left = [(0.10, 0.10, 0.45, 0.30), (0.10, 0.32, 0.45, 0.60), (0.10, 0.62, 0.45, 0.90)]
    right = [(0.55, 0.10, 0.90, 0.40), (0.55, 0.42, 0.90, 0.70), (0.55, 0.72, 0.90, 0.90)]
    boxes = [left[0], right[0], left[1], right[1], left[2], right[2]]
    assert _order(boxes) == [0, 2, 4, 1, 3, 5]


def test_a_title_across_both_columns_is_read_before_them():
    boxes = [
        (0.55, 0.20, 0.90, 0.90),   # right column
        (0.10, 0.20, 0.45, 0.90),   # left column
        (0.10, 0.05, 0.90, 0.10),   # a title across both
    ]
    assert _order(boxes) == [2, 1, 0]


def test_a_band_of_two_sides_is_read_before_what_is_under_it():
    # the Intel 3000 manual's A.C. characteristics: "TEST CONDITIONS:" and
    # its text on the left, "TEST LOAD CIRCUIT:" and its drawing on the
    # right, "CAPACITANCE" and its table across under both
    boxes = [
        (0.13, 0.61, 0.27, 0.62),   # TEST CONDITIONS:
        (0.12, 0.63, 0.47, 0.69),   # its text
        (0.13, 0.75, 0.33, 0.77),   # CAPACITANCE - listed before the right side
        (0.13, 0.78, 0.90, 0.85),   # its table
        (0.51, 0.61, 0.67, 0.62),   # TEST LOAD CIRCUIT:
        (0.53, 0.63, 0.64, 0.71),   # its drawing
    ]
    assert _order(boxes) == [0, 1, 4, 5, 2, 3]


def test_a_heading_hanging_out_left_stays_in_its_column():
    # "PUSH IX" clear of its paragraph's left edge by less than a gutter,
    # a second instruction under the first
    boxes = [
        (0.14, 0.12, 0.20, 0.14),   # PUSH IX
        (0.21, 0.14, 0.72, 0.30),   # its paragraph
        (0.14, 0.40, 0.20, 0.42),   # PUSH IY
        (0.21, 0.42, 0.72, 0.60),   # its paragraph
    ]
    assert _order(boxes) == [0, 1, 2, 3]


def test_labels_down_a_margin_are_no_column():
    # side notes too few to run down as a column: each read by its row
    boxes = [
        (0.05, 0.10, 0.12, 0.12),   # note
        (0.20, 0.10, 0.90, 0.30),   # text
        (0.05, 0.50, 0.12, 0.52),   # note
        (0.20, 0.50, 0.90, 0.70),   # text
    ]
    assert _order(boxes) == [0, 1, 2, 3]
