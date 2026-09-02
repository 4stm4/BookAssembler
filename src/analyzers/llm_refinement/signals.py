"""llm_refinement: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import logging

logger = logging.getLogger(__name__)

BATCH_SIZE = 3

REQUEST_TIMEOUT = 300

VALID_TYPES = {
    "paragraph", "table_cell", "caption", "toc_entry",
    "code", "heading", "formula", "list_item", "unknown",
}
