"""toc: recognising and parsing table-of-contents lines — no KRM writes."""

import re
from typing import List, Optional, Tuple

from src.analyzers.toc.signals import (
    MAX_TOC_TEXT_LEN,
    _ENDS_WITH_PAGE_NUM,
    _LEADING_NUM_RE,
    _SECTION_MARKER_RE,
    _TOC_HEADING_RE,
)


def is_toc_heading(text: str) -> bool:
    return bool(_TOC_HEADING_RE.match(text or ""))


_BARE_PAGE_NUM_RE = re.compile(r"^\s*(\d{1,4}|[ivxlcdm]+)\s*$", re.IGNORECASE)


def is_bare_page_number(text: str) -> bool:
    """A line that is nothing but a folio number — "42", "vii"."""
    return bool(_BARE_PAGE_NUM_RE.match(text or ""))


def parse_entry(text: str) -> Tuple[str, Optional[str], Optional[int]]:
    """Split "1.2  Registers .......... 45" into
    (entry_text, chapter_number, target_page).

    entry_text keeps the displayed wording minus dot-leaders; the other two
    are parsed extras and may be None (a TOC with no page numbers is still a
    TOC — see is_toc_entry).
    """
    stripped = re.sub(r"\.{2,}", " ", (text or "").strip())
    stripped = re.sub(r"\s+", " ", stripped)

    target_page: Optional[int] = None
    m_page = _ENDS_WITH_PAGE_NUM.search(stripped)
    if m_page:
        raw = m_page.group(1)
        try:
            target_page = int(raw) - 1  # 0-based physical page index
        except ValueError:
            target_page = None  # roman numerals — leave unparsed for now
        stripped = _ENDS_WITH_PAGE_NUM.sub("", stripped).strip()

    chapter_number: Optional[str] = None
    m_num = _LEADING_NUM_RE.match(stripped)
    if m_num:
        if m_num.group("hier"):
            chapter_number = m_num.group("hier")
        elif m_num.group("letter"):
            chapter_number = m_num.group("letter") + "."
        elif m_num.group("roman"):
            chapter_number = m_num.group("roman") + "."
        elif m_num.group("word"):
            chapter_number = f"{m_num.group('word')} {m_num.group('word_num')}"

    return stripped, chapter_number, target_page


def _has_title_word(text: str) -> bool:
    words = [w for w in text.split() if len(w) >= 3 and any(c.isalpha() for c in w)]
    return len(words) >= 1


def is_toc_entry(text: str, *, anchored: bool = False) -> bool:
    """Does this line look like a contents entry?

    Three accepted shapes, because a real TOC is not always the dotted-leader
    kind:
      1. "… Registers .......... 45" — ends with a page number;
      2. "Section 2  Machine Utilisation" / "Appendix B  Staff" — a section
         marker lead;
      3. "1.2  Registers" — a hierarchical number lead.

    `anchored` loosens the rule: once a "Contents" heading has been seen, any
    short non-sentence line counts, so a bare "Introduction" under the heading
    is not lost.
    """
    stripped = (text or "").strip()
    if not stripped or len(stripped) > MAX_TOC_TEXT_LEN or len(stripped) < 3:
        return False
    if is_bare_page_number(stripped):
        # A running folio ("vii", "42") sitting alone on its own line — the
        # front-matter page number next to a real "Table of Contents"
        # header, not an entry.
        return False

    if _ENDS_WITH_PAGE_NUM.search(stripped):
        title_part = _ENDS_WITH_PAGE_NUM.sub("", stripped).strip()
        return _has_title_word(title_part)

    if _LEADING_NUM_RE.match(stripped) and _has_title_word(stripped):
        return True

    if anchored:
        # No number, no page — accepted only right after the heading. Reject
        # anything that reads as a sentence.
        if stripped.endswith((".", "!", "?", ":")) and len(stripped.split()) > 6:
            return False
        return _has_title_word(stripped)

    return False


def split_merged_entries(line: str) -> List[str]:
    """A column layout can mash several entries into one text run:
    "Section 3 Application Development 3.1 Academic 3.2 Library Section 4 …".

    Split before every embedded section marker. A line with a single entry
    comes back unchanged.
    """
    stripped = re.sub(r"\s+", " ", (line or "").strip())
    if not stripped:
        return []

    cuts = [m.start() for m in _SECTION_MARKER_RE.finditer(stripped)]
    # The first marker at position 0 is this line's own lead, not a boundary.
    cuts = [c for c in cuts if c > 0]
    if not cuts:
        return [stripped]

    parts, prev = [], 0
    for c in cuts:
        seg = stripped[prev:c].strip()
        if seg:
            parts.append(seg)
        prev = c
    tail = stripped[prev:].strip()
    if tail:
        parts.append(tail)
    return parts or [stripped]
