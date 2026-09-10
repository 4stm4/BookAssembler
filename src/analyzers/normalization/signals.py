"""normalization: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_WS_RE = re.compile(r"\s+")
