"""bibliography: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_BIB_TITLES = (
    "bibliography", "references", "works cited", "литература",
    "библиография", "список литературы", "источники",
)

_NUMBERED_RE = re.compile(r"^\s*\[(?P<n>\d+)\]\s*(?P<rest>.*)$")

_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2}|21\d{2})\b")
