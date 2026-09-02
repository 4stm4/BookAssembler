"""algorithm: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_ALGO_PREFIX_RE = re.compile(
    r"^\s*(?:algorithm|алгоритм)\s+(?P<number>\d+(?:\.\d+)*)\s*[.:—–\-]?\s*(?P<name>.*)$",
    re.IGNORECASE,
)

_PSEUDO_KEYWORDS = re.compile(
    r"\b(?:if|then|else|while|for|do|end|return|input|output|repeat|until|procedure|function)\b",
    re.IGNORECASE,
)
