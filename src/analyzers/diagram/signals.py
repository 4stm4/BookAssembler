"""diagram: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import logging
import re

log = logging.getLogger(__name__)

# A real figure caption block starts with "Figure N-M" / "Fig. N.M" - or
# "Figure N." and its title ("Figure 2. 3002 Block Diagram"), the number
# misread now and then: the MCS-40 manual's "Figure 1-2." came out
# "Figure '·2.".
_RE_FIGURE_CAPTION = re.compile(r"^fig(?:ure|\.)?\s*(?:\d+[-.–]\d+|[^\s\d]{0,3}\d+[.:](?=\s))", re.IGNORECASE)

_RE_SUBLABEL = re.compile(r"^\(?[a-g]\)?\s+\w", re.IGNORECASE)  # (a) Immediate

MIN_LABELS = 6          # min short labels in a region to call it a diagram

MAX_LABEL_WORDS = 4     # a "label" is a short text block

MAX_LABEL_WIDTH = 0.30  # schematic labels are narrow; body text spans wider

# Body text runs on in lines this many characters long on average and
# more; a figure's labels OCR ran together into one block ("MEMORY EXT
# DATA IN DEVICE IN" over four rows of the Intel 3000 manual's block
# diagram), its wires read as letters ("CLX -I L,---.---"), in short ones.
PROSE_LINE_CHARS = 20

# Of its figure's caption's size, the size of text set so much smaller it
# is the figure's own - its notes ("(1) IO instructions control the flow
# of information...", 4.3pt in the MCS-40 manual's 4004 instruction cycle,
# its caption 7.6pt), no body text bounding it.
NOTE_SIZE = 0.8

# Graphic boxes/arrows extend past the text labels, so pad generously — most on
# the right where destination boxes (Memory/Datum) sit beyond the last label.
RIGHT_PAD = 0.17

LEFT_PAD = 0.05

PAD = 0.03
