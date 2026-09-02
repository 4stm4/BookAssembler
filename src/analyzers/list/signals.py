"""list: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_BULLET_CHARS = "•·‣∙◦▪▫■□●○*\\-–—"

_MARKER_RE = re.compile(
    r"""^\s*
    (?:
        (?P<bullet>[""" + _BULLET_CHARS + r"""])
      | (?P<num>\d{1,3})[.)]
      | (?P<alpha>[a-zа-я])[.)]
      | (?P<roman>[ivxlcdm]+)[.)]
    )
    \s+
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
