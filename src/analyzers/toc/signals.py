"""toc: what marks a table of contents — headings, entry shapes, thresholds.

These are the attributes by which the entity is recognised. The methods that
apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

# The heading that opens a contents page. Matched against a short, stripped
# line — "CONTENTS", "Table of Contents", "Оглавление", "Содержание".
_TOC_HEADING_RE = re.compile(
    r"^\s*(?:table\s+of\s+)?contents\s*$"
    r"|^\s*оглавление\s*$"
    r"|^\s*содержание\s*$",
    re.IGNORECASE,
)

# Leading chapter number: "1", "1.2", "1.2.3", "A.", "IV.", "Глава 5",
# "Chapter 7", "Section 2", "Appendix B".
_LEADING_NUM_RE = re.compile(
    r"""^\s*
    (?:
        (?P<hier>\d+(?:\.\d+){0,3}\.?)                       # 1 | 1. | 1.2 | 1.2.3
      | (?P<letter>[A-ZА-ЯЁa-zа-яё])[.)]                     # A.  a.  А)
      | (?P<roman>[IVXLCDM]+)[.)]                            # IV.  X)
      | (?P<word>(?:Глава|Chapter|Часть|Part|Раздел|Section|Appendix|Приложение))\s+
        (?P<word_num>[\d\wА-Яа-я]+)
    )
    \s+
    """,
    re.VERBOSE,
)

# The same section markers, findable anywhere in a line — used to split a run
# of entries that a column layout mashed into one text block
# ("Section 3 … 3.1 … 3.2 … Section 4 …").
_SECTION_MARKER_RE = re.compile(
    r"(?<!\S)"
    r"(?:"
    r"(?:Глава|Chapter|Часть|Part|Раздел|Section|Appendix|Приложение)\s+[\dA-ZА-Я]+\b"
    r"|\d+(?:\.\d+){1,3}\b"                                  # 3.1  3.2.1 — but not bare "3"
    r")",
)

# Trailing page reference: digits or roman numerals at end of line.
_ENDS_WITH_PAGE_NUM = re.compile(r"\s(\d{1,4}|[ivxlcdm]+|[IVXLCDM]+)\s*$")

# A run this long is a TOC even without a "Contents" heading to anchor it.
MIN_TOC_RUN = 4

# Entry lines are short. A line longer than this is prose, not a TOC entry.
MAX_TOC_TEXT_LEN = 120

# A real TOC sits near the front (or, for indexes-as-contents, the back). A
# run whose average page falls outside these fractions is rejected unless a
# "Contents" heading anchors it.
TOC_PAGE_FRACTION = 0.12

# The heading trigger ("CONTENTS"/"Table of Contents" as a standalone line)
# is looser than the entry rules — a two-column table header split into
# lines ("Location" / "Contents"), or the bare word inside a code comment,
# both satisfy it. A proportional front window does not save this on a long
# book: TOC_PAGE_FRACTION of 585 pages is 70, well past where an unrelated
# "Contents" cell can occur. A real table of contents starts within the first
# couple dozen pages regardless of the book's length — this caps the window
# in absolute pages, measured on the Zilog Z80 manual where stray matches at
# pages 33/42/295/297 each restarted an anchored run over ordinary prose.
TOC_HEADING_MAX_PAGE = 20
