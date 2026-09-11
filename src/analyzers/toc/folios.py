"""toc: the book's own page numbers — printed label → page index in the file.

A contents entry prints where it points ("45", "xiii", "2-15"); the file
indexes its pages from 0, and front matter shifts one against the other —
by an amount that can change inside a book (a plate or a blank page without
a folio). Measuring the shift on the entries that link to a heading failed
on half the test books: no headings found (TeX Live guide), only diagram
debris for headings (MCS-40), a title shared by two sections (Buildroot),
a shift that changes mid-book (Zilog Z80). The numbers printed on the pages
themselves say where each label is.

Pure functions; the linker gathers the page-edge texts.
"""

import re
from typing import Dict, Iterable, List, Optional, Tuple

# A page's own number sits in its top or bottom band, at the start or end
# of a short line — alone ("vii"), or with the running head ("1 ВВЕДЕНИЕ
# 3", "Page 12"). The Zilog Z80 manual prints it at y=0.11.
EDGE_TOP = 0.13
EDGE_BOTTOM = 0.88
MAX_EDGE_TEXT = 80

# Numbers at a page's edge that are not its folio are many on a scan: table
# cells, diagram labels, the telephone numbers of sales offices (Signetics:
# 500 candidates over 106 pages). The folios are the ones that form a chain
# through the book: the number grows with the page, and the shift between
# them moves only in small steps — a plate without a folio adds a page, a
# page the scan missed takes one away (Intel 3000, chapter 2: 8 → 7 → 6).
# The longest such chain is the book's numbering; a chain this short is no
# numbering at all.
MIN_CHAIN = 3
MAX_SHIFT_STEP = 8

# "2-15" as printed; a scan's OCR reads the hyphen as a raised dot as often
# as not ("2·15", "1·35" — Intel 3000, MCS-40). A full stop is not taken:
# "3.1" at the top of a page is a section heading.
_LABEL_RE = re.compile(r"^(?:(?P<ch>\d{1,3})[-–·‧](?P<n>\d{1,4})|(?P<ar>\d{1,4})|(?P<ro>[ivxlcdm]{1,7}))$")
# Debris OCR leaves on a folio ("3-9·", "12'"). Not a colon or a comma: "2:"
# at a page's foot is a footnote marker (MetaPost), "8," a table cell.
_TOKEN_JUNK = ".'’`·‧"
# "58 / 139", "12 of 40" — the page and the count (Buildroot's running head).
_OF_TOTAL_RE = re.compile(r"(?:^|\s)(\d{1,4})\s*(?:/|of|из)\s*\d{1,4}\s*$", re.IGNORECASE)
_ROMAN = (("m", 1000), ("cm", 900), ("d", 500), ("cd", 400), ("c", 100), ("xc", 90),
          ("l", 50), ("xl", 40), ("x", 10), ("ix", 9), ("v", 5), ("iv", 4), ("i", 1))
_ROMAN_RE = re.compile(r"^m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")


def _roman(s: str) -> Optional[int]:
    if not s or not _ROMAN_RE.match(s):
        return None
    total, i = 0, 0
    for sym, val in _ROMAN:
        while s.startswith(sym, i):
            total, i = total + val, i + len(sym)
    return total


def parse_label(label: str) -> Optional[Tuple[str, int]]:
    """"45" → ("", 45); "xiii" → ("r", 13); "2-15" → ("c2", 15)."""
    m = _LABEL_RE.match((label or "").strip().strip(_TOKEN_JUNK))
    if not m:
        return None
    if m.group("ch"):
        return "c" + str(int(m.group("ch"))), int(m.group("n"))
    if m.group("ar"):
        return "", int(m.group("ar"))
    value = _roman(m.group("ro"))
    return ("r", value) if value else None


def folio_candidates(text: str) -> List[str]:
    """The tokens at the start and the end of a page-edge line that could be
    the page's number."""
    tokens = (text or "").split()
    if not tokens or len(text) > MAX_EDGE_TEXT:
        return []
    of_total = _OF_TOTAL_RE.search(text)
    if of_total:
        return [of_total.group(1)]
    ends = {tokens[0], tokens[-1]}
    return [t for t in ends if parse_label(t)]


def _longest_chain(points: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """The longest run of (page, number) — pages rising, numbers rising, the
    shift page − number moving by at most MAX_SHIFT_STEP from one point to
    the next. Among equally long runs, the one whose shift moves least."""
    if not points:
        return []
    best: List[Tuple[int, int]] = [(1, 0)] * len(points)   # (length, -total shift change)
    prev: List[int] = [-1] * len(points)
    for i, (pi, ni) in enumerate(points):
        for j in range(i):
            pj, nj = points[j]
            step = abs((pi - ni) - (pj - nj))
            if pj < pi and nj < ni and step <= MAX_SHIFT_STEP:
                cand = (best[j][0] + 1, best[j][1] - step)
                if cand > best[i]:
                    best[i], prev[i] = cand, j
    i = max(range(len(points)), key=lambda k: best[k])
    chain = []
    while i != -1:
        chain.append(points[i])
        i = prev[i]
    return chain[::-1]


class PageMap:
    """Printed page label → page index, from the folios printed on pages."""

    def __init__(self, folios: Iterable[Tuple[int, str]]) -> None:
        by_kind: Dict[str, List[Tuple[int, int]]] = {}
        for page, label in folios:
            parsed = parse_label(label)
            if parsed:
                kind, n = parsed
                by_kind.setdefault(kind, []).append((n, page))
        self._points: Dict[str, List[Tuple[int, int]]] = {}
        for kind, pts in by_kind.items():
            chain = _longest_chain(sorted({(p, n) for n, p in pts}))
            # A real change of shift inside a book (a page inserted without a
            # folio) holds for the pages after it; a stray number that merely
            # fits the chain holds for its own page only (MCS-40, page 50).
            shifts = [p - n for p, n in chain]
            held = [pt for pt, s in zip(chain, shifts) if shifts.count(s) >= 2]
            chain = held or chain
            if len(chain) >= MIN_CHAIN:
                self._points[kind] = sorted((n, p) for p, n in chain)

    def __bool__(self) -> bool:
        return bool(self._points)

    def resolve(self, label: str) -> Optional[int]:
        """The page index that carries `label` — read off the page, or, for
        a page without a readable folio, from the neighbours around it."""
        parsed = parse_label(label)
        if not parsed:
            return None
        kind, n = parsed
        pts = self._points.get(kind)
        if not pts:
            return None
        exact = [p for m, p in pts if m == n]
        if exact:
            return exact[0]
        below = [pt for pt in pts if pt[0] < n]
        above = [pt for pt in pts if pt[0] > n]
        ref = max(below) if below else min(above)
        return n + (ref[1] - ref[0])
