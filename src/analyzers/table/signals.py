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

_SEPARATOR_RE = re.compile(r"^[\s\-_=|+:·.─━┃│┼┤├┬┴]{3,}$")

_TAB_SPLIT_RE = re.compile(r"\t|  {2,}|(?:\s{2,}\|?\s{2,})")
