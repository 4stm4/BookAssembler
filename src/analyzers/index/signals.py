"""index: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_INDEX_TITLE_RE = re.compile(
    r"^(?:index|указатель|предметный\s+указатель|subject\s+index)$",
    re.IGNORECASE,
)

_INDEX_ENTRY_RE = re.compile(
    r"^(?P<term>.+?)\s*,\s*(?P<pages>(?:\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*)?)+)\s*$"
)
