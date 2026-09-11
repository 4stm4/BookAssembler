"""Table of contents — read from the contents pages' geometry.

An entry is a row that points to a page. The shapes below were each met on
one of the ten test books (docs/deploy/testing-the-pipeline.md): dotted,
spaced and OCR'd leaders; a page far from its title with no leader at all;
number, title and page as separate PDF lines; two columns; titles wrapped
onto a second line; a margin label beside the list; annotation lines under
an entry; front-matter and chapter-page numbering.
"""

from typing import List, Optional, Tuple

import pytest

from src.analyzers import create_default_pipeline
from src.analyzers.heading import HeadingAnalyzer
from src.analyzers.toc import TocAnalyzer, TocLinkAnalyzer
from src.analyzers.toc.layout import Line, read_toc
from src.analyzers.toc.rules import (
    is_folio,
    is_toc_heading,
    join_wrapped,
    split_number,
    split_trailing_page,
    strip_leaders,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyleDescriptor,
    StyledTextSpan,
    TextLineInline,
    TocEntryBlock,
    VisualLayout,
)

H = 0.012      # line height, page-normalised
CW = 0.007     # character width
RIGHT = 0.85   # where a right-aligned page reference ends


def dot(x: float, y: float, left: str, page: str) -> Tuple[float, float, str, float]:
    """A dotted-leader line filled out to the right margin, as typeset."""
    n = max(3, int((RIGHT - x) / CW) - len(left) - len(page) - 2)
    return x, y, f"{left} {'.' * n} {page}".strip(), RIGHT


def _box(spec) -> Tuple[float, float, str, float]:
    x, y, text = spec[:3]
    return x, y, text, (spec[3] if len(spec) > 3 else min(1.0, x + CW * len(text)))


# --- text rules ------------------------------------------------------------

@pytest.mark.parametrize("line, body, page", [
    ("Registers . . . . . . 45", "Registers . . . . . .", "45"),
    ("Revision History. . . . . .iii", "Revision History. . . . . .", "iii"),
    ("3002 Central Processing Element ...... 2-15", "3002 Central Processing Element ......", "2-15"),
    ("Z80 HARDWARE ORGANIZATION �46", "Z80 HARDWARE ORGANIZATION �", "46"),
    ("Page i", "Page i", None),               # a footer, not an entry
    ("Migrating to 2016.11", "Migrating to 2016.11", None),   # a version
])
def test_split_trailing_page(line, body, page):
    assert split_trailing_page(line) == (body, page)


@pytest.mark.parametrize("raw, title", [
    ("Readline Init File. . . . . . . .", "Readline Init File"),
    ("Foreword........................", "Foreword"),
    ("The boot hangs after Starting network...  .  .  .", "The boot hangs after Starting network..."),
    ("Why doesn’t Buildroot generate binary packages (.deb, .ipkg...)?   .  .", "Why doesn’t Buildroot generate binary packages (.deb, .ipkg...)?"),
    ("I. � BASIC CONCEPTS �", "I. BASIC CONCEPTS"),
    ("Addressing Microcontral Memory. ..... .... . . .", "Addressing Microcontral Memory"),
])
def test_strip_leaders(raw, title):
    assert strip_leaders(raw) == title


@pytest.mark.parametrize("text, number, rest", [
    ("26.1 Caveat with automatic UIDs", "26.1", "Caveat with automatic UIDs"),
    ("27.10Migration to 2026.02", "27.10", "Migration to 2026.02"),
    ("10.1.1 2003", "10.1.1", "2003"),
    ("A. BUILDING OS/8 FOR THE SBC6120", "A.", "BUILDING OS/8 FOR THE SBC6120"),
    ("Chapter 3 Signetics Microassembler", "Chapter 3", "Signetics Microassembler"),
    ("3001 Microprogram Control Unit", None, "3001 Microprogram Control Unit"),
])
def test_split_number(text, number, rest):
    assert split_number(text) == (number, rest)


@pytest.mark.parametrize("text, ok", [
    ("Contents", True), ("Table of Contents", True), ("Содержание", True),
    ("Оглавление", True), ("TABlE or conTEnTS", True),   # Signetics 8080, OCR
    ("consents", False), ("Contents of the register", False),
])
def test_toc_heading(text, ok):
    assert is_toc_heading(text) is ok


def test_folio_and_hyphenation():
    assert is_folio("Page i") and is_folio("vii") and not is_folio("Pin Functions")
    assert join_wrapped("Параметрическая работа с пу-", "тями") == "Параметрическая работа с путями"
    assert join_wrapped("3216/3226 Parallel Bi-Directional", "Bus Driver") == \
        "3216/3226 Parallel Bi-Directional Bus Driver"


# --- geometry -------------------------------------------------------------

class Page:
    """Builds the Lines of synthetic contents pages; one block per call."""

    def __init__(self) -> None:
        self.pages: dict = {}
        self._idx = 0
        self._block = 0

    def block(self, page: int, *lines, size: float = 10.0) -> int:
        for spec in lines:
            x, y, text, x1 = _box(spec)
            ln = Line(self._idx, text, x, y, x1, y + H, size, page, self._block)
            self.pages.setdefault(page, []).append(ln)
            self._idx += 1
        self._block += 1
        return self._block - 1

    def read(self):
        return read_toc(self.pages)


def _texts(toc) -> List[Tuple[Optional[str], str, Optional[str]]]:
    return [(*e.number_and_title(), e.page_label) for e in toc.entries]


def test_dotted_leaders_one_line_each():
    p = Page()
    p.block(2, (0.3, 0.05, "CONTENTS"))
    p.block(2, dot(0.15, 0.10, "1 OVERVIEW", "1"),
            dot(0.17, 0.12, "1.1 REGULATORY WARNING", "2"),
            dot(0.15, 0.14, "2 ASSEMBLY", "3"))
    toc = p.read()
    assert _texts(toc) == [("1", "OVERVIEW", "1"), ("1.1", "REGULATORY WARNING", "2"),
                           ("2", "ASSEMBLY", "3")]
    assert [e.level for e in toc.entries] == [1, 2, 1]


def test_number_title_and_page_as_separate_lines():
    """texinfo and asciidoc output: three PDF lines on one baseline."""
    p = Page()
    p.block(1, (0.1, 0.05, "Contents"))
    y = 0.10
    for num, title, page in (("1", "About Buildroot", "2"), ("2", "System requirements", "3"),
                             ("2.1", "Mandatory packages", "3"), ("3", "Getting Buildroot", "5")):
        x = 0.10 if "." not in num else 0.12
        p.block(1, (x, y, num), (x + 0.03, y, title), (0.94, y, page))
        y += 0.03
    toc = p.read()
    assert _texts(toc) == [("1", "About Buildroot", "2"), ("2", "System requirements", "3"),
                           ("2.1", "Mandatory packages", "3"), ("3", "Getting Buildroot", "5")]


def test_no_leader_and_a_wide_gap():
    """MCS-40: the page stands far right of its title, nothing between, and
    the column of page numbers is a block of its own."""
    p = Page()
    p.block(2, (0.05, 0.05, "Contents"))
    p.block(2, *[(0.05, 0.10 + 0.02 * i, t) for i, t in enumerate(
        ["INTRODUCTION", "Economics of Using Microcomputers", "CHAPTER 1. PROCESSORS"])])
    p.block(2, *[(0.44, 0.10 + 0.02 * i, t, 0.46) for i, t in enumerate(["iii", "iii", "1-1"])])
    assert [e.page_label for e in p.read().entries] == ["iii", "iii", "1-1"]


def test_two_columns():
    p = Page()
    p.block(2, (0.1, 0.05, "Содержание"))
    left = [("1", "Введение", "2"), ("2", "Базовые команды", "4"), ("3", "Управление выводом", "5")]
    right = [("9", "Продвинутая графика", "33"), ("10", "Макросы", "54"), ("11", "Циклы", "65")]
    for i, ((ln, lt, lp), (rn, rt, rp)) in enumerate(zip(left, right)):
        y = 0.10 + 0.025 * i
        p.block(2, (0.15, y, ln), (0.17, y, lt), (0.47, y, lp, 0.48),
                (0.52, y, rn), (0.55, y, rt), (0.84, y, rp, 0.85))
    toc = p.read()
    assert _texts(toc) == [(n, t, pg) for n, t, pg in left + right]


def test_heading_level_with_the_other_columns_first_entry():
    """MetaPost: "Содержание" top-left, level with the right column's first
    entry — which is contents, not part of the heading's band."""
    p = Page()
    p.block(2, (0.15, 0.080, "Содержание", 0.29))
    p.block(2, (0.52, 0.085, "9"), (0.545, 0.085, "Продвинутая графика"), (0.84, 0.085, "33", RIGHT))
    for i in range(3):
        y = 0.11 + 0.02 * i
        p.block(2, (0.15, y, str(i + 1)), (0.17, y, f"Раздел {i + 1}"), (0.47, y, str(i + 2), 0.48),
                (0.545, y, f"9.{i + 1}"), (0.58, y, f"Пункт {i + 1}"), (0.84, y, str(35 + i), RIGHT))
    toc = p.read()
    assert [t for _, t, _ in _texts(toc)] == [
        "Раздел 1", "Раздел 2", "Раздел 3", "Продвинутая графика", "Пункт 1", "Пункт 2", "Пункт 3"]


def test_wrapped_title_gets_its_page_from_the_last_line():
    p = Page()
    p.block(2, (0.4, 0.05, "Contents"))
    p.block(2, (0.43, 0.10, "3214 Interrupt Control Unit"), dot(0.69, 0.10, "", "2-49"),
            (0.43, 0.12, "3216/3226 Parallel Bi-Directional"),
            dot(0.445, 0.14, "Bus Driver", "2-61"),
            dot(0.43, 0.16, "APPLICATIONS", "3-1"))
    toc = p.read()
    assert _texts(toc) == [(None, "3214 Interrupt Control Unit", "2-49"),
                           (None, "3216/3226 Parallel Bi-Directional Bus Driver", "2-61"),
                           (None, "APPLICATIONS", "3-1")]


def test_margin_label_beside_the_list_is_not_read_into_it():
    """Intel Series 3000: "Series 3000 / Reference / Manual" on the same
    baselines, left of the list, in blocks of its own."""
    p = Page()
    p.block(2, (0.41, 0.05, "Contents"))
    p.block(2, (0.23, 0.10, "Series 3000"))
    p.block(2, (0.25, 0.12, "Reference"))
    p.block(2, dot(0.41, 0.10, "INTRODUCTION", "1-1"),
            dot(0.41, 0.12, "COMPONENT FAMILY", "2-1"),
            dot(0.43, 0.14, "3001 Microprogram Control Unit", "2-1"))
    assert [t for _, t, _ in _texts(p.read())] == [
        "INTRODUCTION", "COMPONENT FAMILY", "3001 Microprogram Control Unit"]


def test_lines_without_a_page_annotate_the_entry_above():
    """Zaks lists each chapter's topics under it; the text is kept."""
    p = Page()
    p.block(7, (0.3, 0.05, "TABLE OF CONTENTS"))
    p.block(7, (0.15, 0.10, "I. �"), (0.23, 0.10, "BASIC CONCEPTS �"), (0.83, 0.10, "15", RIGHT))
    p.block(7, (0.26, 0.13, "Introduction, What is programming?, Flowcharting, Informa-"),
            (0.26, 0.145, "tion Representation"))
    p.block(7, (0.15, 0.20, "H. �"), (0.23, 0.20, "Z80 HARDWARE ORGANIZATION �46", RIGHT))
    p.block(7, (0.15, 0.25, "V."), (0.23, 0.25, "ADDRESSING TECHNIQUES �"),
            (0.82, 0.25, "438", RIGHT))
    toc = p.read()
    assert [e.page_label for e in toc.entries] == ["15", "46", "438"]
    assert toc.entries[0].description == [
        "Introduction, What is programming?, Flowcharting, Information Representation"]


def test_a_page_of_mostly_annotation_continues_the_contents():
    """Zaks, page 8: five chapters, three topic lines under each — the page
    is contents through and through, though entries are a fifth of it."""
    p = Page()
    p.block(7, (0.3, 0.07, "TABLE OF CONTENTS"))
    p.block(7, *[dot(0.15, 0.10 + 0.03 * i, f"{r}. CHAPTER {r}", str(10 * i + 13))
                 for i, r in enumerate(("I", "II", "III"))])
    y = 0.08
    for r in ("VI", "VII", "VIII", "IX", "X"):
        p.block(8, dot(0.10, y, f"{r}. CHAPTER {r}", str(len(r) * 100)))
        p.block(8, *[(0.21, y + 0.022 * (k + 1), f"Introduction, Topic {k}, More Topics,") for k in range(3)])
        y += 0.11
    toc = p.read()
    assert toc.pages == [7, 8]
    assert len(toc.entries) == 8
    assert len(toc.entries[3].description) == 1   # three wrapped lines, one annotation


def test_page_furniture_and_column_header_are_not_entries():
    p = Page()
    p.block(2, (0.3, 0.05, "CONTENTS"))
    p.block(2, (0.42, 0.08, "Page"))
    p.block(2, dot(0.15, 0.10, "1 OVERVIEW", "1"),
            dot(0.15, 0.12, "2 ASSEMBLY", "3"),
            dot(0.15, 0.14, "3 HARDWARE", "11"))
    p.block(2, (0.40, 0.93, "Page i"))
    assert [t for _, t, _ in _texts(p.read())] == ["OVERVIEW", "ASSEMBLY", "HARDWARE"]


def test_contents_run_over_pages_and_stop_at_the_next_list():
    """Zilog Z80: "List of Figures" follows at the page margin, laid out
    exactly like the contents."""
    p = Page()
    p.block(4, (0.1, 0.05, "Table of Contents"))
    for page in (4, 5):
        p.block(page, *[dot(0.2, 0.10 + 0.02 * i, f"Section {page}{i}", str(10 * page + i))
                        for i in range(4)])
    p.block(6, (0.1, 0.05, "List of Figures"))
    p.block(6, *[dot(0.2, 0.10 + 0.02 * i, f"Figure {i}", str(i + 1)) for i in range(4)])
    toc = p.read()
    assert toc.pages == [4, 5]
    assert len(toc.entries) == 8


def test_contents_end_mid_page_at_the_first_heading():
    """TeX Live guide: the list ends and "1 Введение" follows, larger."""
    p = Page()
    p.block(0, (0.1, 0.05, "Содержание"))
    p.block(0, *[dot(0.15, 0.10 + 0.02 * i, f"{i + 1} Раздел {i + 1}", str(i + 2))
                 for i in range(4)])
    p.block(0, (0.12, 0.30, "1"), (0.15, 0.30, "Введение"), size=14.3)
    p.block(0, (0.12, 0.33, "В этом документе описаны основные возможности программного "
                             "продукта TEX Live — дистрибутива TEXа и других программ", RIGHT))
    toc = p.read()
    assert len(toc.entries) == 4
    assert not any("Введение" == e.number_and_title()[1] for e in toc.entries)


def test_ocr_heading_and_headingless_contents():
    p = Page()
    p.block(1, (0.4, 0.05, "TABlE or conTEnTS"))
    p.block(1, *[dot(0.1, 0.10 + 0.02 * i, f"Chapter {i} Topic", str(i * 7 + 3))
                 for i in range(1, 4)])
    assert len(p.read().entries) == 3

    q = Page()
    q.block(0, (0.1, 0.3, "A cover page"))
    q.block(2, *[(0.05, 0.10 + 0.02 * i, f"Topic number {i}") for i in range(8)])
    q.block(2, *[(0.44, 0.10 + 0.02 * i, f"{i + 1}-1", 0.46) for i in range(8)])
    toc = q.read()
    assert toc.heading is None and len(toc.entries) == 8


def test_an_all_digit_title_run_out_in_a_leader():
    """TeX Live guide: "10.1.1 2003 . . . . . ." with the page apart from it."""
    p = Page()
    p.block(0, (0.1, 0.07, "Содержание"))
    for i, (num, year, page) in enumerate((("10.1", "Прошлое", "34"), ("10.1.1", "2003", "34"),
                                           ("10.1.2", "2004", "35"), ("10.2", "2014", "40"))):
        y = 0.10 + 0.015 * i
        p.block(0, (0.15, y, f"{num} {year} " + ". " * 25, 0.84), (0.86, y, page, 0.875))
    assert _texts(p.read()) == [("10.1", "Прошлое", "34"), ("10.1.1", "2003", "34"),
                                ("10.1.2", "2004", "35"), ("10.2", "2014", "40")]


def test_a_number_run_into_its_title_is_split_by_the_sequence():
    """TeX Live guide: "10.1.102013" — the number box too narrow for 10.1.10."""
    p = Page()
    p.block(0, (0.1, 0.07, "Содержание"))
    for i, (text, page) in enumerate((("10.1.9 2012", "39"), ("10.1.102013", "40"),
                                      ("10.2 2014", "40"))):
        p.block(0, dot(0.15, 0.10 + 0.015 * i, text, page))
    assert _texts(p.read()) == [("10.1.9", "2012", "39"), ("10.1.10", "2013", "40"),
                                ("10.2", "2014", "40")]


def test_roman_numbers_misread_by_ocr_are_restored_by_the_sequence():
    """Zaks: "I. H. HI. IV." in the text layer is "I. II. III. IV." in print."""
    p = Page()
    p.block(7, (0.3, 0.07, "TABLE OF CONTENTS"))
    for i, (num, title, page) in enumerate((("I.", "BASIC CONCEPTS", "15"),
                                            ("H.", "Z80 HARDWARE ORGANIZATION", "46"),
                                            ("HI.", "BASIC PROGRAMMING TECHNIQUES", "94"),
                                            ("IV.", "THE Z80 INSTRUCTION SET", "154"))):
        p.block(7, dot(0.15, 0.10 + 0.03 * i, f"{num} {title}", page))
    assert _texts(p.read()) == [("I.", "BASIC CONCEPTS", "15"),
                                ("II.", "Z80 HARDWARE ORGANIZATION", "46"),
                                ("III.", "BASIC PROGRAMMING TECHNIQUES", "94"),
                                ("IV.", "THE Z80 INSTRUCTION SET", "154")]


def test_a_misread_numeral_out_of_sequence_is_left_as_printed():
    p = Page()
    p.block(7, (0.3, 0.07, "TABLE OF CONTENTS"))
    for i, (num, page) in enumerate((("I.", "15"), ("HI.", "46"), ("IV.", "94"))):
        p.block(7, dot(0.15, 0.10 + 0.03 * i, f"{num} CHAPTER", page))
    assert [n for n, _, _ in _texts(p.read())] == ["I.", None, "IV."]


def test_a_page_after_a_plain_space_at_the_column_edge():
    """MetaPost: a justified column fills the line up to its page number."""
    p = Page()
    p.block(2, (0.15, 0.07, "Содержание"))
    p.block(2, (0.15, 0.10, "5"), (0.17, 0.10, "Линейные уравнения"), (0.47, 0.10, "15", 0.48))
    p.block(2, (0.17, 0.12, "5.1"), (0.21, 0.12, "Уравнения и координатные пары 15", 0.48))
    p.block(2, (0.17, 0.14, "5.2"), (0.21, 0.14, "Работа с неизвестными . . . . ."),
            (0.47, 0.14, "17", 0.48))
    assert _texts(p.read()) == [("5", "Линейные уравнения", "15"),
                                ("5.1", "Уравнения и координатные пары", "15"),
                                ("5.2", "Работа с неизвестными", "17")]


def test_a_one_dot_leader_between_a_long_title_and_its_page():
    """MetaPost: the title nearly fills the line; one dot is all the leader
    left, drawn as a line of its own."""
    p = Page()
    p.block(2, (0.55, 0.07, "Содержание"))
    p.block(2, (0.545, 0.10, "10.1 Группировка . . . . . . . . . . .", 0.82), (0.837, 0.10, "55", 0.853))
    p.block(2, (0.545, 0.115, "10.2 Параметризованные макросы", 0.802), (0.816, 0.115, ".", 0.82),
            (0.837, 0.115, "56", 0.853))
    p.block(2, (0.545, 0.13, "10.3 Суффиксные и текстовые пара-", 0.811),
            (0.582, 0.145, "метры . . . . . . . . . . . . . . .", 0.82), (0.837, 0.145, "59", 0.853))
    assert _texts(p.read()) == [("10.1", "Группировка", "55"),
                                ("10.2", "Параметризованные макросы", "56"),
                                ("10.3", "Суффиксные и текстовые параметры", "59")]


def test_a_running_head_in_the_margin_is_not_an_entry():
    """Buildroot: "The Buildroot user manual  ii" at the top of every
    contents page, its folio at the same right edge as the page numbers."""
    p = Page()
    for page in (1, 2):
        p.block(page, (0.1, 0.045, "The Buildroot user manual"), (0.94, 0.045, "ii", RIGHT))
    p.block(1, (0.1, 0.15, "Contents"))
    p.block(1, *[dot(0.1, 0.20 + 0.02 * i, f"{i + 1} Chapter {i + 1}", str(i + 2)) for i in range(3)])
    p.block(2, *[dot(0.1, 0.10 + 0.02 * i, f"{i + 4} Chapter {i + 4}", str(i + 9)) for i in range(3)])
    assert [t for _, t, _ in _texts(p.read())] == [f"Chapter {i}" for i in range(1, 7)]


def test_a_stop_in_one_column_keeps_the_other():
    """MetaPost: the book's first heading starts under both columns."""
    p = Page()
    p.block(2, (0.15, 0.07, "Содержание"))
    for i in range(3):
        y = 0.10 + 0.02 * i
        p.block(2, (0.15, y, str(i + 1)), (0.17, y, f"Левая {i + 1}"), (0.47, y, str(i + 2), 0.48),
                (0.52, y, str(i + 9)), (0.55, y, f"Правая {i + 9}"), (0.84, y, str(i + 40), RIGHT))
    p.block(2, (0.15, 0.30, "1"), (0.17, 0.30, "Введение"), size=14.3)
    assert [t for _, t, _ in _texts(p.read())] == [
        "Левая 1", "Левая 2", "Левая 3", "Правая 9", "Правая 10", "Правая 11"]


def test_a_contents_word_in_a_diagram_does_not_hide_the_real_list():
    """MCS-40 has no contents heading; "CONTENTS" labels a register in a
    diagram on page 11."""
    p = Page()
    p.block(2, *[(0.05, 0.10 + 0.02 * i, f"Topic number {i}") for i in range(8)])
    p.block(2, *[(0.44, 0.10 + 0.02 * i, f"{i + 1}-1", 0.46) for i in range(8)])
    p.block(11, (0.6, 0.4, "CONTENTS"))
    p.block(11, (0.3, 0.45, "ADDRESS TO MEMORY"))
    toc = p.read()
    assert toc.pages == [2] and len(toc.entries) == 8


def test_a_short_numbered_list_deep_in_the_book_is_not_a_toc():
    p = Page()
    p.block(50, *[dot(0.2, 0.10 + 0.02 * i, f"1.{i} Something", str(i + 3)) for i in range(4)])
    assert read_toc(p.pages).entries == []


# --- the analyzers on a KRM document ------------------------------------

def _para(page: int, *lines, size: float = 10.0) -> ParagraphBlock:
    inlines = []
    boxes = [_box(spec) for spec in lines]
    for x, y, text, x1 in boxes:
        vl = VisualLayout(
            bounding_box=NormalizedRect(x, y, x1, y + H),
            page_or_screen_index=page,
            style=StyleDescriptor(font_family="serif", font_size_pt=size),
        )
        il = TextLineInline(spans=[StyledTextSpan(text=text, visual_layout=vl)])
        il.visual_layout = vl
        inlines.append(il)
    return ParagraphBlock(
        inlines=inlines,
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(min(b[0] for b in boxes), min(b[1] for b in boxes),
                                        max(b[3] for b in boxes), max(b[1] for b in boxes) + H),
            page_or_screen_index=page,
            style=StyleDescriptor(font_family="serif", font_size_pt=size),
        ),
    )


def _doc(children) -> Tuple[KnowledgeDocument, ContainerUnit]:
    root = ContainerUnit(title="book", level=1, children=children)
    return KnowledgeDocument(title="t", source_uri="test://", root_containers=[root]), root


def _contents_page():
    heading = _para(1, (0.1, 0.05, "Contents"), size=18)
    entries = _para(1, dot(0.1, 0.10, "1 Introduction", "1"),
                    dot(0.1, 0.12, "2 Registers", "5"),
                    dot(0.12, 0.14, "2.1 Flags", "7"))
    return heading, entries


def test_analyzer_builds_a_container_and_tombstones_the_source():
    heading, entries = _contents_page()
    body = _para(3, (0.1, 0.5, "The report proper begins here."))
    doc, root = _doc([heading, entries, body])
    TocAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

    toc = root.children[0]
    assert isinstance(toc, ContainerUnit) and toc.semantic_type == "toc"
    assert toc.title == "Contents"
    got = [(e.chapter_number, e.entry_text, e.page_label, e.level) for e in toc.children]
    assert got == [("1", "Introduction", "1", 1), ("2", "Registers", "5", 1),
                   ("2.1", "Flags", "7", 2)]
    # RFC 0001 §2.4: kept in place, tombstoned with a reason — never removed
    assert root.children[1:] == [heading, entries, body]
    assert heading.is_tombstoned and entries.is_tombstoned and not body.is_tombstoned
    assert entries.metadata["tombstone_reason"] == "merged_into_toc"
    # An entry never reuses a tombstoned source's id.
    ids = {e.id for e in toc.children}
    assert len(ids) == 3 and not ids & {heading.id, entries.id}


def test_a_block_holding_more_than_contents_stays_live():
    heading = _para(0, (0.1, 0.05, "Содержание"), size=14)
    mixed = _para(0, dot(0.1, 0.10, "1 Введение", "2"),
                  dot(0.1, 0.12, "2 Структура", "4"),
                  dot(0.1, 0.14, "3 Установка", "7"),
                  (0.1, 0.20, "В этом документе описаны основные возможности программного "
                              "продукта TEX Live — дистрибутива TEXа и других программ", RIGHT))
    doc, root = _doc([heading, mixed])
    TocAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    assert len(root.children[0].children) == 3
    assert not mixed.is_tombstoned


def test_heading_tree_is_still_built_around_the_contents():
    heading, entries = _contents_page()
    ch1 = _para(3, (0.1, 0.1, "Introduction"), size=20)
    text = _para(3, (0.1, 0.2, "Body text of the chapter."))
    doc, root = _doc([heading, entries, ch1, text] + [
        _para(4 + i, (0.1, 0.2, "More body text.")) for i in range(5)])
    TocAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    HeadingAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    titles = [c.title for c in root.children if isinstance(c, ContainerUnit)]
    assert "Introduction" in titles, "a contents container must not stop the tree"


def test_linker_anchors_entries_and_measures_the_page_shift():
    ch1 = ContainerUnit(title="1 Introduction", level=1,
                        visual_layout=VisualLayout(NormalizedRect(0, 0, 1, 1), 14))
    ch2 = ContainerUnit(title="2 Registers", level=1,
                        visual_layout=VisualLayout(NormalizedRect(0, 0, 1, 1), 18))
    toc = ContainerUnit(title="Contents", level=2, semantic_type="toc",
                        visual_layout=VisualLayout(NormalizedRect(0, 0, 1, 1), 4), children=[
        TocEntryBlock(entry_text="Introduction", chapter_number="1", page_label="1"),
        TocEntryBlock(entry_text="Registers", chapter_number="2", page_label="5"),
        TocEntryBlock(entry_text="Appendix", page_label="30"),
        TocEntryBlock(entry_text="Preface", page_label="iii"),
    ])
    doc = KnowledgeDocument(title="t", source_uri="test://",
                            root_containers=[ContainerUnit(title="book", children=[toc, ch1, ch2])])
    TocLinkAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    e = toc.children
    assert (e[0].anchor_id, e[1].anchor_id) == (ch1.id, ch2.id)
    assert (e[0].target_page, e[1].target_page) == (14, 18)
    assert e[2].target_page == 43          # printed 30 + the measured shift of 13
    assert e[3].target_page is None        # nothing to measure a roman shift against


def test_linker_measures_chapter_page_numbering_per_chapter():
    ch = ContainerUnit(title="COMPONENT FAMILY", level=1,
                       visual_layout=VisualLayout(NormalizedRect(0, 0, 1, 1), 20))
    toc = ContainerUnit(title="Contents", semantic_type="toc", children=[
        TocEntryBlock(entry_text="COMPONENT FAMILY", page_label="2-1"),
        TocEntryBlock(entry_text="3002 Central Processing Element", page_label="2-15"),
    ])
    doc = KnowledgeDocument(title="t", source_uri="test://",
                            root_containers=[ContainerUnit(title="book", children=[toc, ch])])
    TocLinkAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    assert [x.target_page for x in toc.children] == [20, 34]


def test_pipeline_reads_contents_before_headings_and_links_after():
    names = [a.manifest.name for a in create_default_pipeline()]
    assert names.index("EphemeraDetectorAnalyzer") < names.index("TocAnalyzer") \
        < names.index("HeadingAnalyzer") < names.index("TocLinkAnalyzer")
