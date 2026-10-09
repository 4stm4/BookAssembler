"""heading: what marks the entity — the shape of a real heading's text.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

# A real word: 3+ letters containing a vowel, not all the same letter. Same
# shape as scan_noise's own check — kept as a separate constant here rather
# than imported, because the two call sites judge text for different
# purposes at different blast radii (see rules.py).
_WORD_RE = re.compile(r"[A-Za-z]{3,}")

# The number a heading leads with - its part's ("4101 RAM" of the MCS-40
# manual), its chapter's - is no noise: its figures count as a word's.
_LEADING_NUMBER_RE = re.compile(r"^\d[\d/.]*")

# A heading promoted from a scanned page can carry an embedded real word
# ("FUNCTION", "NOTE") inside what is otherwise diagram-label or code-comment
# noise ("FUNCTION;' FUM~g~N BUS ' I INPUTS F, DECOOER F,"). One real word is
# not enough evidence; most of the TEXT must be made of real words.
#
# Measured against the Intel Series 3000 manual (1976, poor scan): real
# headings scored 0.77-1.0. Garbage split in two: symbol/digit-heavy noise
# scored 0.0-0.45 (rejected below); a harder half — a diagram label or code
# comment built around one genuine English word, e.g. "'* INITIALIZATION
# SEQUENCE" — scored 0.5-0.92, overlapping the real headings' own range.
# Text shape alone cannot separate that half from a real heading; this
# threshold catches the unambiguous case without risking a real one.
MIN_WORD_CHAR_RATIO = 0.5

# The word-ratio threshold cannot reach the harder half — a code comment or
# diagram label built around one genuine word scores in the same range as a
# real heading. Those carry their own tells instead:
#
# A source-code comment mangled by OCR: "/*" misread as "'*", "1*", "!*";
# its close "*/" misread as "*'", "*,". A real chapter heading does not open
# or close this way.
_COMMENT_OPEN_RE = re.compile(r"^['/1!]\*")
_COMMENT_CLOSE_RE = re.compile(r"\*['/,]?\s*$")

# An inline annotation, not a section title — a real TOC/heading essentially
# never opens with the literal word "NOTE:".
_NOTE_PREFIX_RE = re.compile(r"^\s*NOTES?\s*:", re.IGNORECASE)

# A diagram label or pinout description trails off into scan noise once the
# real words run out: "PIN SYMBOL NAME AND TYPE FUNCTION R=- = }--". Three or
# more non-alphanumeric characters running up to the end of the line is not
# how a heading ends.
_TRAILING_JUNK_RE = re.compile(r"[^A-Za-z0-9\s]{3,}\s*$")

# A heading in body size, told by its weight alone (rules._is_printed_heading):
# a run of bold words longer than this is a paragraph's bold line, not a
# title. The paragraph fixtures' longest is "CAS BEFORE RAS REFRESH COUNTER
# TEST", six.
MAX_PRINTED_HEADING_WORDS = 10
# How far under it, in its own line's heights, the paragraph a heading heads
# begins.
MAX_HEADING_GAP_LINES = 3.0
# How far left of the paragraph under it, in its own line's heights, a
# heading hangs to stand apart by place alone: "PUSH IX" hangs 3.5.
HANGING_INDENT_LINES = 2.0
# A heading set larger than its page's body stands so much larger at the
# least: the MCS-40 manual's "THE FUNCTIONS OF A COMPUTER" 1.22 of its
# 7.4pt body, its noise between lines of one size 0.03-0.06.
LARGER_THAN_BODY = 1.12
# A line read larger than the body prints its words at least this heavy
# against the text around it (printed "weight"): set larger, a heading's
# strokes are as wide as the body's and wider - 1.00-2.0 on the heading
# fixtures. One lighter is small type OCR ran rows of together, read
# larger: the MCS-40 manual's timing diagram labels "ENABLE / INHIBIT",
# 0.6.
LARGER_MIN_WEIGHT = 0.9
# A line set smaller than this of the body is a diagram's label, a
# footnote's - no heading (the Intel 3000 manual's block diagram labels
# stand at 0.5-0.8 of its body).
SMALLER_THAN_BODY = 0.9
# The most lines a heading prints in: the MCS-40 manual's "PROGRAM COUNTER
# (JUMPS, SUBROUTINES AND / THE STACK):" takes two.
MAX_HEADING_LINES = 2
# Headings whose sizes stand within this of each other are of one size
# (their levels go by their case and slant): 7.39 to 7.85pt in the MCS-40
# manual for one style read at different heights of a scan.
SAME_HEADING_SIZE = 1.08
# A row of this many lines standing apart, side by side, is a table's
# column heads ("Pin No.", "Designation", "Description of Function" over
# the MCS-40 manual's pin table) - no headings. Two headings may stand
# side by side ("TEST CONDITIONS:", "TEST LOAD CIRCUIT:" of the Intel 3000
# manual).
HEAD_ROW_CELLS = 3
# Of the lower of two lines' height, how much of it they share to stand
# on one row.
SAME_ROW = 0.5
# Lines a block's each column takes for the block to be two columns' text
# OCR ran together: the MCS-40 manual's "Basic Timing" and its paragraph
# beside "1. Address Register (Program Counter & Stack) & Address /
# Incrementer". A row of a label table ("States: 15  Flags: none") is one.
COLUMN_LINES = 2
# Words of a line of running text, one of which each such column holds -
# a table's columns of cells ("1,7,8,11", "Y0-Y7", "Active") none.
COLUMN_WORDS = 5
