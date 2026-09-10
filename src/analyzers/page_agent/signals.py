"""page_agent: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import logging
import time

log = logging.getLogger(__name__)

MIN_NUMERIC_RATIO = 0.35  # numeric density hint (real tables have ≥35% numeric)

MIN_BLOCKS = 5            # need enough blocks to look like a grid

MIN_SHORT_RATIO = 0.7     # most blocks are short (labels/cells, not paragraphs)

# One systematically bad page must not abort the book, but a dead agent should
# stop the run rather than time out once per page.
FAILURE_BUDGET_RATIO = 0.35

MIN_FAILURE_BUDGET = 3
