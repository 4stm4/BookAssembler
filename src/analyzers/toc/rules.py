"""toc: reading a contents line as text — no geometry, no KRM writes."""

import re
from typing import Optional, Tuple

from src.analyzers.toc.signals import (
    FUZZY_HEADING_MAX_EDITS,
    LEADER_CHARS,
    PROSE_MIN_CHARS,
    PROSE_MIN_WORDS,
    _FOLIO_RE,
    _FUZZY_HEADINGS,
    _LEADING_NUMBER_RE,
    _NUMBER_TOKEN_RE,
    _ENDS_WITH_LEADER_RE,
    _PAGE_RE,
    _SPACED_PAGE_RE,
    _STOP_HEADING_RE,
    _TOC_HEADING_RE,
    _TRAILING_PAGE_RE,
)

_LEADER_SET = frozenset(LEADER_CHARS)


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def is_toc_heading(text: str) -> bool:
    """"Contents", "Table of Contents", "Содержание" — or an OCR reading of
    the long forms a couple of letters off ("TABlE or conTEnTS")."""
    t = (text or "").strip()
    if _TOC_HEADING_RE.match(t):
        return True
    letters = "".join(c for c in t.lower() if c.isalpha())
    return any(
        abs(len(letters) - len(h)) <= FUZZY_HEADING_MAX_EDITS
        and _edit_distance(letters, h) <= FUZZY_HEADING_MAX_EDITS
        for h in _FUZZY_HEADINGS
    )


def is_stop_heading(text: str) -> bool:
    """The heading of the next front-matter list ("List of Figures")."""
    return bool(_STOP_HEADING_RE.match(text or ""))


def is_page_ref(text: str) -> bool:
    """A bare printed page reference: "45", "xiii", "2-15"."""
    return bool(_PAGE_RE.match((text or "").strip()))


def is_folio(text: str) -> bool:
    """The page's own number or footer ("Page i", "vii") — not an entry."""
    return bool(_FOLIO_RE.match(text or ""))


def is_number_token(text: str) -> bool:
    """A section number standing alone ("1.2.1", "IV.", "A.")."""
    return bool(_NUMBER_TOKEN_RE.match((text or "").strip()))


def is_leader_only(text: str) -> bool:
    t = (text or "").replace(" ", "")
    return bool(t) and all(c in _LEADER_SET for c in t)


def is_prose(text: str) -> bool:
    t = (text or "").strip()
    return len(t) >= PROSE_MIN_CHARS or len(t.split()) >= PROSE_MIN_WORDS


def normalize_page(page: str) -> str:
    """"2 - 15" and "2–15" print the same reference as "2-15"."""
    return re.sub(r"\s*[-–]\s*", "-", (page or "").strip())


def split_trailing_page(text: str) -> Tuple[str, Optional[str]]:
    """"Registers . . . . 45" → ("Registers . . . .", "45").

    Only after a leader character: a line ending in a bare space and a
    number is not a contents entry ("Page i" in a footer).
    """
    m = _TRAILING_PAGE_RE.match(text or "")
    if not m:
        return text, None
    return m.group("body").rstrip(), normalize_page(m.group("page"))


def split_spaced_page(text: str) -> Tuple[str, Optional[str]]:
    """"Уравнения и координатные пары 15" → ("Уравнения и координатные пары", "15").

    For a line already known to reach its column's right edge; on its own a
    trailing number after a space proves nothing.
    """
    m = _SPACED_PAGE_RE.match(text or "")
    if not m:
        return text, None
    return m.group("body").rstrip(), normalize_page(m.group("page"))


def ends_with_leader(text: str) -> bool:
    """"10.1.1 2003 . . . . . ." — a title (even an all-digit one) run out
    to its page number."""
    return bool(_ENDS_WITH_LEADER_RE.search((text or "").rstrip()))


def strip_leaders(text: str) -> str:
    """The title without the leader run that fills the line to its page.

    Leader tokens are dropped wherever they stand ("I. � BASIC CONCEPTS �",
    as OCR read Zaks); a run glued to the last word goes when it is spaced,
    long, or not made of dots. An ellipsis that belongs to the title stays
    ("Starting network...  .  .  ."), a lone full stop the leader began with
    does not ("Readline Init File. . . ." — texinfo draws it that way).
    """
    tokens = (text or "").split()
    kept = [t for t in tokens if not is_leader_only(t)]
    removed = len(kept) != len(tokens)
    t = " ".join(kept)
    while t:
        m = re.search("[" + re.escape(LEADER_CHARS) + "]+$", t)
        if not m:
            break
        run = m.group(0)
        if len(run) >= 4 or set(run) - {"."}:
            t = t[:m.start()].rstrip()
            removed = True
        else:
            break
    if removed and t.endswith(".") and not t.endswith(".."):
        t = t[:-1].rstrip()
    return t


def split_number(text: str) -> Tuple[Optional[str], str]:
    """"26.1 Caveat with…" → ("26.1", "Caveat with…"); no number → (None, text).

    A number glued to its title by a tight TeX box ("27.10Migration") is
    split before the capital.
    """
    m = _LEADING_NUMBER_RE.match((text or "").strip())
    if not m:
        return None, (text or "").strip()
    return m.group("num").strip(), m.group("rest").strip()


def join_wrapped(first: str, second: str) -> str:
    """Join a title wrapped onto the next line, undoing a hyphenation break
    ("пу-" + "тями" → "путями") but not a real hyphen ("Bi-Directional")."""
    a, b = first.rstrip(), second.lstrip()
    if len(a) >= 2 and a.endswith("-") and a[-2].isalpha() and b[:1].islower():
        return a[:-1] + b
    return f"{a} {b}".strip()
