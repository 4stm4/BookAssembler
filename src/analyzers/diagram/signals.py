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

# A figure of a scanned page is drawn from its own ink (metadata
# "printed_ink"), read at this zoom (pixels to the point) - about the
# scan's own resolution - where its pixels are darker than INK_LEVEL
# (0-255 grey, as a print's words are read, printed._INK_LEVEL).
FIGURE_ZOOM = 4.0
INK_LEVEL = 160
# Of its page, the pixels a block not of the figure is masked out by round
# its box: a caption, a running head standing in the figure's band.
MASK_PAD = 0.002

# --- A drawing found by the page's own ink (ink.py) ----------------------
# Lengths are in ems: the page's body size.

# A drawing's stroke runs this long at the least - longer than the text's
# letters are tall, or two that touch are wide.
STROKE = 2.0
# Of an em, how far about a straight line a rule's ink spreads at the most:
# a table's rule, a rule across the page, an arrow's shaft are no drawing
# of their own - a waveform's pulses, a pen's mark spread wider.
RULE_SPREAD = 0.06
# Of its box, what of a stroke stands in running text for the stroke to be
# a mark on the text: a line struck through, a pen's underline, letters
# that touch.
TEXT_COVER = 0.5
# Of a stroke's box, what the letters standing in it cover where it is a
# mark on lines of text: the pen's underlines 0.27 and 0.31 of theirs, the
# most a drawing's stroke has of its labels 0.14 (the MCS-40 manual's 4004
# instruction cycle).
LETTERED = 0.2
# Strokes this near one another are one drawing.
GAP = 2.0
# A figure is this far across and down at the least, a stroke this long in
# it: a line of large letters that touch, a bracket are none.
FIGURE = 3.0
LONG = 5.0
# A table's frame is ruled across and down: FRAME_RULED of its ink lies on
# rules RULE long or more, and FRAME_SPAN of their length each way on rules
# that run the frame's whole width or height (FRAME_WHOLE of it, their
# pieces within LINE_SPREAD of one row taken together). A block diagram's
# boxes stand apart, its rules stop short; a circuit's, a waveform's
# strokes are no rules.
RULE = 1.5
FRAME_RULED = 0.9
FRAME_SPAN = 0.5
FRAME_WHOLE = 0.9
LINE_SPREAD = 0.25
# A letter's ink is this tall at the least - a dot, a comma, a dash are
# no measure of a line's letters.
SPECK = 0.15
# Text this near a drawing's strokes is its label, whatever its print:
# "Vcc" at the end of the Intel 3000 manual's test load circuit's wire,
# set as large as the heading over it, a line and a half off. And ink no
# line of the page's text accounts for, this near the figure, is its own.
TOUCH = 0.5
# Text set small (SMALLER of the body's size) this near a drawing - as it
# stands with the labels by it - is its label or its note.
REACH = 1.5
SMALLER = 0.9
# A figure's note stands between it and its caption in this many lines of
# running text at the most ("Note: Some Shift and Rotate instructions do
# not include the Carry." over Zaks' "Fig. 2.3"); more is the page's
# text, and the caption another figure's.
NOTE_LINES = 2
