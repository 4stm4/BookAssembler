"""table: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import logging
import re

log = logging.getLogger(__name__)

MIN_TABLE_ROWS = 3

Y_STEP_TOLERANCE = 0.012

X_OVERLAP_THRESHOLD = 0.25

MAX_CELL_TEXT_LEN = 120

MAX_BLOCK_HEIGHT = 0.05

# A single-column table's rows (bullet lists, appendix TOCs) run short; a
# wrapped prose paragraph's lines run close to the full column width. Above
# this, a single-column single-block candidate is read as prose, not a table
# (RFC 0001 §2.4 - a real page had a 7-line paragraph averaging 85 chars/line
# misread as a table before this existed).
_SINGLE_COL_PROSE_LEN = 60

_SEPARATOR_RE = re.compile(r"^[\s\-_=|+:·.─━┃│┼┤├┬┴]{3,}$")

_TAB_SPLIT_RE = re.compile(r"\t|  {2,}|(?:\s{2,}\|?\s{2,})")
