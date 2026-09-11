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
