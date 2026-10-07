"""list: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_BULLET_CHARS = "•·‣∙◦▪▫■□●○*\\-–—"

# A number set off by a dash, the item's first word right after it - "1—insert
# key in the keyhole" (the paragraph fixture B) - is a marker as "1." is.
_MARKER_RE = re.compile(
    r"""^\s*
    (?:
        (?P<bullet>[""" + _BULLET_CHARS + r"""])\s+
      | (?P<num>\d{1,3})(?:[.)]\s+|\s*[—–]\s*(?=\w))
      | (?P<alpha>[a-zа-я])[.)]\s+
      | (?P<roman>[ivxlcdm]+)[.)]\s+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
