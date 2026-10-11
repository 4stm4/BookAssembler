"""title_page: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from src.krm.models import BlankPageBlock, ContainerUnit, KnowledgeDocument, ParagraphBlock, TitlePageBlock, TextLineInline, StyledTextSpan

log = logging.getLogger(__name__)

MAX_SCAN_PAGES = 12

MIN_SCORE = 3

# Title/copyright pages live at the very front. Beyond this, ALL-CAPS section
# headings (CONTENTS, SECTION 1, …) must NOT be mistaken for title pages.
TITLE_MAX_PAGES = 3

# A title page is short centered lines; a content page has running paragraphs.
MAX_TITLE_BLOCK_LEN = 150

# A title page is a few lines on a page mostly white. The Intel 3000
# manual's 3003 page, cut out as a page of its own - a pin table, a logic
# diagram's labels, its equations, headings in capitals over them, seventy
# lines and none longer than MAX_TITLE_BLOCK_LEN - was taken for one.
MAX_TITLE_LINES = 30

# A title page is words - its title, its authors, its publisher: a block
# with no word of three letters is a number, a unit. A page more than this
# share of whose blocks are such is a table's - the Intel 3000 manual's
# "A.C. CHARACTERISTICS", capitals over columns of "50 27", "ns ns ns".
MAX_WORDLESS = 1 / 3
_RE_WORD = re.compile(r"[^\W\d_]{3,}")

_RE_STRONG = re.compile(
    r"\b(university|college|institute|laborator|press|publisher|inc\.|"
    r"annual\s+report|thesis|dissertation|proceedings|edition|isbn|copyright)\b",
    re.IGNORECASE,
)

_RE_COPYRIGHT = re.compile(r"(?:©|\bcopyright\b|\bcopr\b)", re.IGNORECASE)

_RE_PUBLISHER = re.compile(
    r"\b(?:press|publisher|inc\.|hall|wiley|springer|mcgraw|elsevier|"
    r"academic|prentice|addison|cambridge|oxford|o'reilly)\b",
    re.IGNORECASE,
)

_RE_ISBN = re.compile(r"\bISBN\b", re.IGNORECASE)

_RE_EDITION = re.compile(r"\b\d+(?:st|nd|rd|th)\s+edition\b", re.IGNORECASE)

_RE_YEAR = re.compile(r"\b(19|20)\d{2}\b")

_NodeLoc = Tuple[Any, ContainerUnit, int]
