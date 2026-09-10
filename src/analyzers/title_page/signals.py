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
