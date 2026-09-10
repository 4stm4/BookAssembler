"""definition: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_DEFINITION_PREFIX_RE = re.compile(
    r"^\s*(?:definition|определение)\s+(?P<number>\d+(?:\.\d+)*)?\s*[.:—–\-]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_DEFINITION_PATTERN_RE = re.compile(
    r"^(?P<term>.{2,60}?)\s+(?:—\s*это|is\s+defined\s+as|is\s+called|means|называется)\s+(?P<def>.+)$",
    re.IGNORECASE,
)
