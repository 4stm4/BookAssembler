"""ephemera: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_PAGENUM_RE = re.compile(r"^\s*(?:\d{1,4}|[ivxlcdm]{1,8}|[IVXLCDM]{1,8})\s*$")

# A running head repeats; below this it is page-specific content.
MIN_REPEAT_PAGES = 2
