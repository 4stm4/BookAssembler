"""footnote: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"

_SUPER_MAP = {c: i for i, c in enumerate(_SUPERSCRIPT_DIGITS)}

_MARKER_RE = re.compile(
    r"""^\s*
    (?:
        (?P<super>[""" + _SUPERSCRIPT_DIGITS + r"""]+)
      | (?P<digit>\d{1,3})[.)]
      | (?P<sym>[*†‡§¶])
    )
    \s+
    """,
    re.VERBOSE,
)
