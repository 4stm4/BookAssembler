"""A figure of a scanned page: where it stands (diagram.rules.figure_area),
how its own ink is drawn (latex_builder._scan_ink), and how it is found by
the page's ink (diagram.ink, diagram.rules.drawings)."""

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


# --- a figure found by the page's own ink (diagram.ink, diagram.rules) ---

import pytest

from src.analyzers.diagram.rules import drawings, is_small
from src.analyzers.diagram.signals import FIGURE_ZOOM

_EM = 10.0                      # the page's body size, pt
_PAGE = (200.0, 200.0)          # pt


def _page(draw):
    """A page of ink, drawn by draw(cv2, canvas) - a white canvas at
    FIGURE_ZOOM, drawn on in black - and read into strokes."""
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from src.analyzers.diagram.ink import strokes_of

    canvas = np.full((int(_PAGE[1] * FIGURE_ZOOM), int(_PAGE[0] * FIGURE_ZOOM)), 255, np.uint8)
    draw(cv2, canvas)
    return np, cv2, strokes_of(np, cv2, canvas < 128, _PAGE, _EM)


def _px(pt: float) -> int:
    return int(pt * FIGURE_ZOOM)


def _box(cv2, canvas, x0, y0, x1, y1):
    cv2.rectangle(canvas, (_px(x0), _px(y0)), (_px(x1), _px(y1)), 0, 2)


def _line(cv2, canvas, x0, y0, x1, y1):
    cv2.line(canvas, (_px(x0), _px(y0)), (_px(x1), _px(y1)), 0, 2)


def test_boxes_joined_by_a_line_are_a_figure():
    from src.analyzers.diagram.ink import drawn, is_figure

    def draw(cv2, canvas):
        _box(cv2, canvas, 20, 40, 70, 80)
        _box(cv2, canvas, 120, 90, 170, 140)
        _line(cv2, canvas, 70, 60, 145, 60)
        _line(cv2, canvas, 145, 60, 145, 90)

    np, cv2, page = _page(draw)
    strokes = drawn(np, page, [])
    assert len(strokes) == 1
    assert is_figure(np, cv2, page, strokes)


def test_a_frame_ruled_across_and_down_is_a_table_s():
    from src.analyzers.diagram.ink import drawn, is_figure

    def draw(cv2, canvas):
        for y in (40, 60, 80, 100, 120):
            _line(cv2, canvas, 20, y, 180, y)
        for x in (20, 70, 120, 180):
            _line(cv2, canvas, x, 40, x, 120)

    np, cv2, page = _page(draw)
    strokes = drawn(np, page, [])
    assert len(strokes) == 1
    assert not is_figure(np, cv2, page, strokes)


def test_a_rule_is_no_drawing_at_whatever_slant():
    from src.analyzers.diagram.ink import drawn

    def draw(cv2, canvas):
        _line(cv2, canvas, 10, 50, 190, 52)     # a rule across the page, the scan askew
        _line(cv2, canvas, 100, 60, 100, 180)   # a rule between two columns

    np, _, page = _page(draw)
    assert drawn(np, page, []) == []


def test_a_stroke_in_running_text_is_a_mark_on_it():
    from src.analyzers.diagram.ink import drawn

    def draw(cv2, canvas):
        # a pen's wave through a paragraph
        for x in range(20, 180, 20):
            _line(cv2, canvas, x, 100, x + 10, 106)
            _line(cv2, canvas, x + 10, 106, x + 20, 100)

    np, _, page = _page(draw)
    assert len(drawn(np, page, [])) == 1
    assert drawn(np, page, [(0.05, 0.4, 0.95, 0.6)]) == []


def test_a_stroke_through_lines_of_letters_is_a_mark_on_them():
    from src.analyzers.diagram.ink import drawn

    def letters(cv2, canvas):
        # three lines of letters OCR read nothing of
        for y in (92, 104, 116):
            for x in range(20, 180, 6):
                cv2.rectangle(canvas, (_px(x), _px(y)), (_px(x + 4), _px(y + 6)), 0, -1)

    def wave(cv2, canvas):
        for x in range(20, 180, 40):
            _line(cv2, canvas, x, 95, x + 20, 119)
            _line(cv2, canvas, x + 20, 119, x + 40, 95)

    np, _, page = _page(wave)
    assert len(drawn(np, page, [])) == 1
    np, _, page = _page(lambda cv2, canvas: (letters(cv2, canvas), wave(cv2, canvas)))
    assert drawn(np, page, []) == []


def test_a_line_of_large_letters_is_no_figure():
    from src.analyzers.diagram.ink import drawn, is_figure

    def draw(cv2, canvas):
        # letters that touch, a line of them: long, and one line tall
        cv2.rectangle(canvas, (_px(20), _px(50)), (_px(120), _px(64)), 0, -1)
        cv2.rectangle(canvas, (_px(40), _px(44)), (_px(60), _px(70)), 0, -1)

    np, cv2, page = _page(draw)
    strokes = drawn(np, page, [])
    assert strokes and not is_figure(np, cv2, page, strokes)


def test_the_marks_by_a_figure_are_its_own_but_for_the_page_s_text():
    from src.analyzers.diagram.ink import with_marks

    def draw(cv2, canvas):
        _box(cv2, canvas, 60, 60, 140, 140)
        for k in range(3):   # a ground's bars under it
            _line(cv2, canvas, 90 + 3 * k, 143 + 3 * k, 110 - 3 * k, 143 + 3 * k)
        cv2.rectangle(canvas, (_px(144), _px(100)), (_px(150), _px(106)), 0, -1)   # a letter of a line beside it

    _, _, page = _page(draw)
    area = (0.3, 0.3, 0.7, 0.7)
    grown = with_marks(page, area, [(0.71, 0.49, 0.9, 0.54)], page.ems(0.5))
    assert grown[3] > 0.74 and grown[:3] == pytest.approx(area[:3], abs=0.01)


def test_a_rule_running_on_past_a_figure_is_no_mark_of_it():
    from src.analyzers.diagram.ink import with_marks

    def draw(cv2, canvas):
        _box(cv2, canvas, 60, 60, 140, 140)
        _line(cv2, canvas, 10, 143, 190, 143)   # a rule across the page, close under it

    _, _, page = _page(draw)
    area = (0.3, 0.3, 0.7, 0.7)
    assert with_marks(page, area, [], page.ems(0.5)) == pytest.approx(area, abs=0.005)


def test_a_figure_s_ink_leaves_out_the_page_s_text_and_a_rule_running_through():
    from src.analyzers.diagram.ink import strokes_ink

    def draw(cv2, canvas):
        _box(cv2, canvas, 60, 60, 140, 140)
        _line(cv2, canvas, 5, 100, 195, 100)                                       # a rule across the page
        cv2.rectangle(canvas, (_px(90), _px(80)), (_px(96), _px(86)), 0, -1)       # a letter of the page's text

    np, _, page = _page(draw)
    area = (0.29, 0.29, 0.71, 0.71)
    ink = strokes_ink(np, page, area, [])
    # the rule is one stroke with the box it crosses, and reaches past the
    # area: the letter alone is left
    assert ink["box"] == pytest.approx([0.45, 0.4, 0.48, 0.43], abs=0.005)

    def apart(cv2, canvas):
        _box(cv2, canvas, 60, 60, 140, 140)
        cv2.rectangle(canvas, (_px(90), _px(80)), (_px(96), _px(86)), 0, -1)

    np, _, page = _page(apart)
    whole = strokes_ink(np, page, area, [])
    masked = strokes_ink(np, page, area, [(0.44, 0.39, 0.49, 0.44)])
    assert whole["box"] == pytest.approx([0.3, 0.3, 0.7, 0.7], abs=0.01)
    assert len(masked["runs"]) < len(whole["runs"])


def test_parts_with_none_of_the_page_s_text_between_are_one_drawing():
    # Zaks' two registers under one caption, a label between them - no
    # text of the page, so not among text
    upper, lower = (0.2, 0.30, 0.8, 0.40), (0.2, 0.50, 0.8, 0.60)
    assert drawings([upper, lower], [], (0.02, 0.02)) == [[0, 1]]
    caption = (0.3, 0.43, 0.7, 0.47)
    assert drawings([upper, lower], [caption], (0.02, 0.02)) == [[0], [1]]


def test_strokes_by_one_another_are_one_drawing_wherever_they_stand():
    a, b = (0.20, 0.30, 0.30, 0.40), (0.31, 0.41, 0.40, 0.50)   # corner to corner
    far = (0.70, 0.70, 0.80, 0.80)                               # neither over nor beside
    assert drawings([a, b, far], [], (0.02, 0.02)) == [[0, 1], [2]]


def test_a_label_is_small_by_its_print_or_by_its_letters():
    # by its print's size
    assert is_small(4.0, 7.6, 3.0, 5.2, "MAIN MEMORY")
    # its print read too large across its drawing's strokes - "ED ENABLE",
    # 9.8pt of a 7.6pt page - its letters' ink small
    assert is_small(9.8, 7.6, 2.8, 5.2, "ED ENABLE")
    # a heading in the body's size
    assert not is_small(7.3, 7.3, 5.1, 5.2, "TEST LOAD CIRCUIT:")
    # no letter of it stands tall: its ink says nothing
    assert not is_small(7.3, 7.3, 3.4, 5.2, "ns")
    # strokes OCR read as letters
    assert is_small(34.4, 7.2, 0.0, 5.2, "I---A,- IV")
