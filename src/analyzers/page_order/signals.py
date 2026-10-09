"""page_order: what a page's layout is read by - its gutters, its columns.

These are the attributes by which the order is decided. The methods that
apply them live in rules.py.
"""

# The narrowest gap between two columns, in the page's lines' heights: the
# MCS-40 manual's gutter is 2.2 of them, the Intel 3000 manual's 1.9, a
# pin table's columns 1.6. A heading hanging out left of its paragraph
# ("PUSH IX", 0.4 of a line clear of it) stands in its column.
GUTTER_LINES = 1.0
# Of the height of what it is cut out of, how much a column's blocks
# cover at the least: a column runs on down. A few labels or side notes
# down a margin are none - the band they stand in reads across.
COLUMN_COVER = 0.3
# Of its page's area, a block covering this much is the scan itself,
# behind its text - no part of its layout.
BACKDROP_COVER = 0.5
