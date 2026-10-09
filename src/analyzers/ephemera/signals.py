"""ephemera: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_PAGENUM_RE = re.compile(r"^\s*(?:\d{1,4}|[ivxlcdm]{1,8}|[IVXLCDM]{1,8})\s*$")

# A running head repeats; below this it is page-specific content.
MIN_REPEAT_PAGES = 2

# On a scanned page, one alone, its running head or foot is told by its
# print where it cannot be by repeating:

# a line at the page's edge led or closed by its page number, the number
# set apart from the rest by this many of its line's heights at the least
# (the Signetics 8080 manual's "20  signetics" foot) - a word space parts
# "Chapter 3", "Figure 2";
FOLIO_GAP = 2.0
# a line at the page's edge set apart from its text by its case or slant
# alone - in capitals or italic, regular, no larger than the body (Zaks'
# "PROGRAMMING THE Z80", "BASIC CONCEPTS"): a heading at a page's head is
# set bolder or larger ("A.C. CHARACTERISTICS AND WAVEFORMS"), body text
# in neither ("The move is completed with the microinstruction fields:");
RUNNING_LARGER = 1.12      # of the body's size, a line this large or larger is no running head
RUNNING_LINES = 2          # the most lines a running head prints in
# of a line of capitals' letters, how many OCR may read lowercase
MISREAD_CAPITALS = 0.125
# a line this long is body text, its size the page's body's
BODY_CHARS = 40
