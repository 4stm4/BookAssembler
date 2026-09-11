"""toc: reading a contents page's geometry — lines → columns → rows → entries.

Pure functions over plain `Line` records; no KRM access. The analyzer builds
the Lines from the document and writes the result back.

A contents entry is a row that points to a page. The page reference sits at
the right edge of its column — printed after a leader ("Registers . . . 45")
or alone, far from its title (MCS-40: "INTRODUCTION            iii"). Rows
with no page are either the wrapped start of an entry whose page comes on a
later line, or annotation under the entry above (Zaks lists each chapter's
topics that way); either way their text is kept.
"""

import re
from dataclasses import dataclass, field
from statistics import median
from typing import Dict, List, Optional, Sequence, Set, Tuple

from src.analyzers.toc.rules import (
    ends_with_leader,
    is_folio,
    is_leader_only,
    is_number_token,
    is_page_ref,
    is_prose,
    is_stop_heading,
    is_toc_heading,
    join_wrapped,
    normalize_page,
    split_number,
    split_spaced_page,
    split_trailing_page,
    strip_leaders,
)
from src.analyzers.toc.signals import (
    MARGIN_BOTTOM,
    MARGIN_TOP,
    COLUMN_GAP,
    CONT_MAX_GAP,
    CONT_TOL_CHARS,
    HEADING_SIZE_RATIO,
    HEADINGLESS_MIN_ENTRIES,
    HEADINGLESS_MIN_SHARE,
    LEVEL_X_TOL,
    MIN_ACCOUNTED_SHARE,
    MIN_COLUMN_REFS,
    MIN_ENTRIES_PER_PAGE,
    PAGE_ATTACH,
    RIGHT_EDGE_TOL,
    ROW_OVERLAP,
    TOC_HEADING_MAX_PAGE,
)


@dataclass(frozen=True)
class Line:
    """One laid-out source line, in page-normalised coordinates."""
    idx: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    page: int
    block: int

    @property
    def h(self) -> float:
        return max(self.y1 - self.y0, 1e-4)

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def cw(self) -> float:
        return (self.x1 - self.x0) / max(len(self.text), 1)


@dataclass
class Row:
    lines: List[Line]                  # left to right, page reference excluded
    page_label: Optional[str] = None
    page_line: Optional[Line] = None   # the reference, when it stands alone
    text: str = ""

    @property
    def x0(self) -> float:
        return self.lines[0].x0

    @property
    def x1(self) -> float:
        return max(l.x1 for l in self.lines)

    @property
    def y0(self) -> float:
        return min(l.y0 for l in self.lines)

    @property
    def y1(self) -> float:
        return max(l.y1 for l in self.lines)

    @property
    def h(self) -> float:
        return median(l.h for l in self.lines)

    @property
    def size(self) -> float:
        return max(l.size for l in self.lines)

    @property
    def all_lines(self) -> List[Line]:
        return self.lines + ([self.page_line] if self.page_line else [])

    def stops(self) -> List[float]:
        """Where a wrapped continuation of this row may start: under any of
        its own lines (number, title), or under the second word of a single
        line ("4001 256 X 8 Mask…" continues under "256")."""
        xs = [l.x0 for l in self.lines]
        first = self.lines[0]
        words = first.text.split(" ", 1)
        if len(words) == 2:
            xs.append(first.x0 + (len(words[0]) + 1) * first.cw)
        return xs


@dataclass
class Entry:
    rows: List[Row]
    page_label: Optional[str] = None
    column_left: float = 0.0
    description: List[str] = field(default_factory=list)
    description_rows: List[Row] = field(default_factory=list)
    level: int = 1
    number_override: Optional[str] = None   # set by the _repair_* passes
    number_skip: int = 0                     # chars of text the override replaces

    @property
    def text(self) -> str:
        out = ""
        for r in self.rows:
            out = join_wrapped(out, r.text) if out else r.text
        return out

    @property
    def lines(self) -> List[Line]:
        return [l for r in self.rows for l in r.all_lines]

    def number_and_title(self) -> Tuple[Optional[str], str]:
        if self.number_override:
            return self.number_override, strip_leaders(self.text[self.number_skip:])
        first = self.rows[0].lines
        if len(first) > 1 and is_number_token(first[0].text):
            num = strip_leaders(first[0].text)
            rest = self.text[len(first[0].text):].strip()
            return num, strip_leaders(rest)
        return split_number(self.text)


@dataclass
class TocRead:
    heading: Optional[Line]
    entries: List[Entry]
    consumed: Set[int]          # line idx: entries, annotation and furniture
    content: Set[int]           # line idx that carry entry or annotation text
    pages: List[int]


# -- pages and columns ----------------------------------------------------

def _same_row(a: Line, b: Line, tol: float) -> bool:
    return abs(a.yc - b.yc) <= tol * max(a.h, b.h)


def _nearest_left(ln: Line, lines: Sequence[Line]) -> Optional[Line]:
    """The line this one follows on its baseline. Judged by where lines
    start, not end: an OCR box can run on over the page number it leads to
    (Zaks: "HI. BASIC PROGRAMMING TECHNIQUES �" ends past its "94")."""
    left = [o for o in lines
            if o is not ln and o.x0 < ln.x0 - 0.002 and _same_row(o, ln, PAGE_ATTACH)]
    return max(left, key=lambda o: o.x0) if left else None


def _page_candidates(lines: Sequence[Line]) -> List[Line]:
    """Lines that may carry a page reference: text ending in leader + page,
    or a bare reference with a title or a leader run to its left. A number
    with nothing but another number before it is a section number of the
    next column (MetaPost: "…графика 33 | 9 Продвинутая…"); a title can be
    all digits as long as it runs out in a leader (TeX Live: "10.1.1 2003
    . . . . | 34"); and a leader can be a single dot of its own when the
    title nearly fills the line (MetaPost: "…макросы | . | 56")."""
    out = []
    for ln in lines:
        t = ln.text.strip()
        if is_page_ref(t):
            left = _nearest_left(ln, lines)
            if left is not None and (
                any(c.isalpha() for c in left.text) or ends_with_leader(left.text)
                or is_leader_only(left.text)
            ):
                out.append(ln)
        elif split_trailing_page(t)[1] is not None:
            out.append(ln)
    return out


def column_edges(lines: Sequence[Line]) -> List[float]:
    """Right edges of the page's columns, from where its page references end."""
    xs = sorted(l.x1 for l in _page_candidates(lines))
    clusters: List[List[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] <= COLUMN_GAP:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [max(c) for c in clusters if len(c) >= MIN_COLUMN_REFS]


def _columns(lines: Sequence[Line], edges: List[float]) -> List[List[Line]]:
    cols: List[List[Line]] = [[] for _ in edges]
    for ln in lines:
        lo = 0.0
        for k, r in enumerate(edges):
            if lo < ln.x0 <= r + RIGHT_EDGE_TOL and ln.x1 <= r + RIGHT_EDGE_TOL:
                cols[k].append(ln)
                break
            lo = r + 0.005
    return cols


def _drop_side_labels(col: List[Line], edge: float) -> List[Line]:
    """A margin label beside the contents (Intel Series 3000: "Series 3000 /
    Reference / Manual" left of the list, on the same baselines) is its own
    block, carries no page reference, and starts left of every block that
    does. Keep only blocks that point to a page or lie within their span."""
    cands = [l for l in _page_candidates(col) if l.x1 >= edge - RIGHT_EDGE_TOL]
    ref_blocks = {l.block for l in cands}
    # A bare page reference can be a block of its own, apart from the title
    # it belongs to (the column of page numbers of a leaderless list): the
    # title's block points to a page just as well.
    for p in cands:
        if is_page_ref(p.text):
            left = _nearest_left(p, col)
            if left is not None:
                ref_blocks.add(left.block)
    if not ref_blocks:
        return []
    left = min(l.x0 for l in col if l.block in ref_blocks)
    by_block: Dict[int, List[Line]] = {}
    for l in col:
        by_block.setdefault(l.block, []).append(l)
    keep: List[Line] = []
    for b, ls in by_block.items():
        if b in ref_blocks or min(l.x0 for l in ls) >= left - RIGHT_EDGE_TOL:
            keep.extend(ls)
    return keep


# -- rows ----------------------------------------------------------------------

def _rows(col: List[Line], edge: float) -> List[Row]:
    cands = {l.idx for l in _page_candidates(col)}
    standalone = [l for l in col if l.idx in cands and is_page_ref(l.text)
                  and l.x1 >= edge - RIGHT_EDGE_TOL]
    loose = {l.idx for l in standalone}
    rows: List[Row] = []
    for ln in sorted((l for l in col if l.idx not in loose), key=lambda l: (l.y0, l.x0)):
        for r in reversed(rows[-3:]):
            ov = min(r.y1, ln.y1) - max(r.y0, ln.y0)
            if ov >= ROW_OVERLAP * min(r.h, ln.h):
                r.lines.append(ln)
                r.lines.sort(key=lambda l: l.x0)
                break
        else:
            rows.append(Row(lines=[ln]))
    # A bare page reference joins the nearest row to its left that has none
    # yet. OCR can set it half a line lower than its title (Zaks appendices).
    for p in sorted(standalone, key=lambda l: l.y0):
        best = min(
            (r for r in rows if r.page_line is None and r.x0 < p.x0
             and abs(r.lines[0].yc - p.yc) <= PAGE_ATTACH * max(r.h, p.h)),
            key=lambda r: abs(r.lines[0].yc - p.yc), default=None,
        )
        if best is not None:
            best.page_line = p
            best.page_label = normalize_page(p.text)
    for r in rows:
        whole = " ".join(l.text for l in r.lines)
        if r.page_label is None and not is_folio(whole):
            last = r.lines[-1]
            if last.x1 >= edge - RIGHT_EDGE_TOL:
                body, page = split_trailing_page(last.text.strip())
                if page is None:
                    body, page = split_spaced_page(last.text.strip())
                if page is not None:
                    r.page_label = page
                    r.text = strip_leaders(" ".join([l.text for l in r.lines[:-1]] + [body]))
                    continue
        r.text = strip_leaders(whole)
    return [r for r in rows if r.text or r.page_label]


# -- entries -----------------------------------------------------------------

def _leading_number(row: Row) -> Optional[str]:
    """The section number a row opens with — a line of its own ("3.1" |
    "Title") or the start of its only line ("10.3 Суффиксные…")."""
    first = row.lines[0].text
    if len(row.lines) > 1 and is_number_token(first):
        return first
    return split_number(first)[0]


def _continues(entry: Entry, row: Row) -> bool:
    """Is `row` the wrapped rest of an entry still waiting for its page?"""
    last = entry.rows[-1]
    if entry.text.rstrip().endswith(":"):
        return False  # a group label ("Additional Parts:"), not a wrap
    if row.y0 - last.y1 > CONT_MAX_GAP * last.h:
        return False
    if _leading_number(row) and _leading_number(entry.rows[0]):
        return False  # the next numbered entry, not a wrap of this one
    cw = median(l.cw for r in entry.rows for l in r.lines)
    tol = CONT_TOL_CHARS * cw
    return any(abs(row.x0 - s) <= tol for s in entry.rows[0].stops())


@dataclass
class PageRead:
    entries: List[Entry]
    consumed: Set[int]
    content: Set[int]
    rows: int                  # rows that are not page furniture
    stopped: bool              # the contents end on this page

    @property
    def accounted(self) -> int:
        """Rows the contents explain: entries and the annotation under them."""
        return sum(len(e.rows) + len(e.description_rows) for e in self.entries)


def _before(ln: Line, heading: Line) -> bool:
    """Is `ln` the contents heading, above it, or beside it in its own
    column? A line level with the heading but in another column is not:
    MetaPost's "Содержание" sits top-left, level with the first entry of
    the right column."""
    if ln.idx == heading.idx or ln.y1 <= heading.y0 + 0.25 * heading.h:
        return True
    overlaps = ln.x0 < heading.x1 and ln.x1 > heading.x0
    return overlaps and ln.y0 < heading.y1 - 0.25 * heading.h


def read_page(lines: Sequence[Line], heading: Optional[Line] = None,
              max_size: float = 0.0) -> PageRead:
    """Entries of one contents page, column by column — below its heading,
    when the page has it."""
    if heading is not None:
        lines = [l for l in lines if not _before(l, heading)]
    # The next front-matter list ends the contents wherever it starts — and
    # its heading can sit left of the entries' column (Zilog Z80: "List of
    # Figures" at the page margin), where the column filter below would
    # mistake it for a margin label and read the list as more contents; or
    # high enough to fall in the margin band that is dropped next.
    stop_y = min((l.y0 for l in lines if is_stop_heading(l.text)), default=None)
    stopped = stop_y is not None
    consumed: Set[int] = {l.idx for l in lines
                          if l.y0 < MARGIN_TOP or l.y0 > MARGIN_BOTTOM}
    lines = [l for l in lines if l.idx not in consumed]
    edges = column_edges([l for l in lines if stop_y is None or l.y0 < stop_y])
    entries: List[Entry] = []
    content: Set[int] = set()
    n_rows = 0
    for edge, col in zip(edges, _columns(lines, edges)):
        # A stop found in one column ends the list below it, not the columns
        # beside it (MetaPost: "1 Введение" starts under both).
        if stop_y is not None:
            col = [l for l in col if l.y0 < stop_y]
        col = _drop_side_labels(col, edge)
        if not col:
            continue
        left = min(l.x0 for l in col)
        pending: Optional[Entry] = None
        col_entries: List[Entry] = []

        def flush(p: Optional[Entry]) -> None:
            if p is None:
                return
            if col_entries:
                col_entries[-1].description.append(p.text)
                col_entries[-1].description_rows.extend(p.rows)
            else:
                # Above the first entry: a column header ("Page") — furniture.
                consumed.update(l.idx for r in p.rows for l in r.all_lines)

        for row in _rows(col, edge):
            if not row.page_label and (not row.text or is_folio(row.text)):
                consumed.update(l.idx for l in row.all_lines)
                continue
            n_rows += 1
            if row.page_label is None and (
                is_stop_heading(row.text) or is_prose(row.text)
                or (max_size and row.size > HEADING_SIZE_RATIO * max_size)
            ):
                stopped = True
                stop_y = row.y0 if stop_y is None else min(stop_y, row.y0)
                break
            if pending is not None and _continues(pending, row):
                pending.rows.append(row)
                if row.page_label:
                    pending.page_label = row.page_label
                    col_entries.append(pending)
                    max_size = max(max_size, pending.rows[0].size)
                    pending = None
                continue
            flush(pending)
            pending = None
            e = Entry(rows=[row], page_label=row.page_label, column_left=left)
            if row.page_label:
                col_entries.append(e)
                max_size = max(max_size, row.size)
            else:
                pending = e
        flush(pending)
        for e in col_entries:
            ids = {l.idx for l in e.lines} | {l.idx for r in e.description_rows for l in r.all_lines}
            consumed |= ids
            content |= ids
        entries.extend(col_entries)
    return PageRead(entries, consumed, content, n_rows, stopped)


def _is_toc_page(p: PageRead, min_entries: int, min_share: float) -> bool:
    """Enough entries, and they explain enough of the page."""
    return len(p.entries) >= min_entries and p.accounted >= min_share * max(p.rows, 1)


def _starts_toc(p: PageRead) -> bool:
    """A contents page found with no heading must be unambiguous: many
    entries, and entries themselves (not annotation) a large share."""
    n = len(p.entries)
    return n >= HEADINGLESS_MIN_ENTRIES and n >= HEADINGLESS_MIN_SHARE * max(p.rows, 1)


def find_headings(pages: Dict[int, List[Line]]) -> List[Line]:
    """Every line within the front pages that reads as a contents heading."""
    return [ln for page in sorted(pages) if page <= TOC_HEADING_MAX_PAGE
            for ln in sorted(pages[page], key=lambda l: l.y0)
            if is_toc_heading(ln.text)]


def read_toc(pages: Dict[int, List[Line]]) -> TocRead:
    """The book's contents list: from its heading (or, without one, the first
    unambiguous contents page) through every following page that continues
    it.

    A heading that opens no list is not the contents heading: the MCS-40
    manual has none, but "CONTENTS" labels a register in two diagrams on
    pages 11 and 18.
    """
    for heading in find_headings(pages):
        toc = _read_from(pages, heading.page, heading)
        if toc.entries:
            return toc
    start = next((p for p in sorted(pages)
                  if p <= TOC_HEADING_MAX_PAGE and _starts_toc(read_page(pages[p]))), None)
    if start is None:
        return TocRead(None, [], set(), set(), [])
    return _read_from(pages, start, None)


def _read_from(pages: Dict[int, List[Line]], start: int,
               heading: Optional[Line]) -> TocRead:
    entries: List[Entry] = []
    consumed: Set[int] = {heading.idx} if heading else set()
    content: Set[int] = set()
    used: List[int] = []
    page = start
    max_size = 0.0
    while page in pages:
        read = read_page(pages[page], heading if page == start else None, max_size)
        first = page == start
        if not first and not _is_toc_page(read, MIN_ENTRIES_PER_PAGE, MIN_ACCOUNTED_SHARE):
            break
        if first and not read.entries:
            break
        entries.extend(read.entries)
        consumed |= read.consumed
        content |= read.content
        used.append(page)
        max_size = max([max_size] + [e.rows[0].size for e in read.entries])
        if read.stopped:
            break
        page += 1

    _repair_glued_numbers(entries)
    _repair_roman_numbers(entries)
    _assign_levels(entries)
    return TocRead(heading, entries, consumed, content, used)


def _next_numbers(prev: str) -> List[str]:
    """Numbers that may follow `prev` in a contents list: its first child,
    the next sibling, the next sibling of each ancestor."""
    parts = prev.split(".")
    out = [prev + ".1"]
    for i in range(len(parts) - 1, -1, -1):
        out.append(".".join(parts[:i] + [str(int(parts[i]) + 1)]))
    return out


_ROMAN_RE = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ROMAN_VALUES = (("M", 1000), ("CM", 900), ("D", 500), ("CD", 400), ("C", 100),
                 ("XC", 90), ("L", 50), ("XL", 40), ("X", 10), ("IX", 9),
                 ("V", 5), ("IV", 4), ("I", 1))
# How OCR misreads the strokes of a roman numeral: "II" run together into
# "H", a stroke taken for a lowercase l or a one.
_ROMAN_OCR = (("H", "II"), ("l", "I"), ("1", "I"), ("|", "I"))
_ROMAN_TOKEN_RE = re.compile(r"^([IVXLCDMHl1|]{1,8})\.$")


def _roman_value(s: str) -> Optional[int]:
    if not s or not _ROMAN_RE.match(s):
        return None
    total, i = 0, 0
    for sym, val in _ROMAN_VALUES:
        while s.startswith(sym, i):
            total, i = total + val, i + len(sym)
    return total


def _to_roman(n: int) -> str:
    out = ""
    for sym, val in _ROMAN_VALUES:
        while n >= val:
            out, n = out + sym, n - val
    return out


def _repair_roman_numbers(entries: List[Entry]) -> None:
    """OCR reads the chapter numbers of a scanned contents list off by a
    stroke: Zaks' "I. II. III. IV." came out as "I. H. HI. IV.". A token
    that is no roman numeral, but becomes exactly the one due next once the
    known misreadings are undone, is that numeral — the sequence around it
    says so. Anything else is left as printed."""
    prev: Optional[int] = None
    for e in entries:
        m = _ROMAN_TOKEN_RE.match(e.text.split(" ", 1)[0])
        if not m:
            continue
        token = m.group(1)
        value = _roman_value(token)
        if value is None and prev is not None:
            fixed = token
            for bad, good in _ROMAN_OCR:
                fixed = fixed.replace(bad, good)
            if _roman_value(fixed) == prev + 1:
                e.number_override, e.number_skip = _to_roman(prev + 1) + ".", len(token) + 1
                value = prev + 1
        if value is not None:
            prev = value


def _repair_glued_numbers(entries: List[Entry]) -> None:
    """A TeX number box too narrow for its number runs it into the title,
    and the text layer has no space to split on: "10.1.102013" (TeX Live
    guide, printed that way too). The number due next in the sequence
    splits it back into "10.1.10" and "2013"."""
    prev: Optional[str] = None
    for e in entries:
        num, _ = e.number_and_title()
        if num is None and prev:
            for cand in _next_numbers(prev):
                if e.text.startswith(cand) and e.text[len(cand):].strip():
                    e.number_override, e.number_skip = cand, len(cand)
                    break
        num, _ = e.number_and_title()
        bare = (num or "").rstrip(".")
        prev = bare if bare and all(p.isdigit() for p in bare.split(".")) else None


def _assign_levels(entries: List[Entry]) -> None:
    """Indentation within the column, then type size: a part and a chapter
    can share an indent and differ only in size (Buildroot)."""
    if not entries:
        return
    offs = sorted({round(e.rows[0].x0 - e.column_left, 4) for e in entries})
    clusters: List[float] = []
    for o in offs:
        if not clusters or o - clusters[-1] > LEVEL_X_TOL:
            clusters.append(o)

    def key(e: Entry) -> Tuple[int, float]:
        o = e.rows[0].x0 - e.column_left
        k = max(i for i, c in enumerate(clusters) if o >= c - LEVEL_X_TOL)
        return k, -round(e.rows[0].size, 0)

    ranks = {k: i + 1 for i, k in enumerate(sorted({key(e) for e in entries}))}
    for e in entries:
        e.level = ranks[key(e)]
