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

# A paragraph wraps to its measure: its lines run one after another across
# the full width, each one run of words. A table's rows are cells apart. A
# line OCR broke at a wide justified space ("problem." | "It must terminate
# in" | "a finite number of steps. This", the paragraph fixtures B, D, E)
# is still one run: its pieces stand a word space apart - up to 1.9 of its
# characters' average width there, beside an overlined "W" - where a
# table's columns stand further. A candidate whose rows are mostly such
# lines is prose - in narrow columns too, where a line holds fewer than
# _SINGLE_COL_PROSE_LEN characters.
_PROSE_SPAN = 0.9         # of the candidate's width a prose line runs across
_PROSE_GAP = 2.5          # of its characters' average width: its widest word space
_PROSE_MIN_WORDS = 5      # words of two letters or more in a prose line

_SEPARATOR_RE = re.compile(r"^[\s\-_=|+:·.─━┃│┼┤├┬┴]{3,}$")

_TAB_SPLIT_RE = re.compile(r"\t|  {2,}|(?:\s{2,}\|?\s{2,})")

# A table of labels and their values: "Cycles: 3 / States: 15 / Flags:
# none" under each instruction of the Z80 manual (the paragraph fixture C),
# a label ending in a colon, its value apart from it in a column of its
# own. Its labels stand within _LABEL_ALIGN of one another across, its
# values too; a value longer than _LABEL_VALUE_LEN is a sentence, no cell.
_LABEL_ALIGN = 0.01
_LABEL_VALUE_LEN = 40
