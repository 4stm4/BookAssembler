"""font_stats: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import logging

log = logging.getLogger(__name__)

_MONO_HINTS = (
    "courier", "consolas", "mono", "menlo", "source code", "fira code",
    "inconsolata", "dejavu sans mono", "liberation mono", "andale",
)

_MATH_HINTS = (
    "cmmi", "cmsy", "cmex", "msam", "msbm", "stix", "symbol", "math",
    "mtmi", "mtsy", "asana", "esint", "yhmath",
)

HEADING_SIZE_RATIO = 1.15

CAPTION_SIZE_RATIO = 0.88

FOOTNOTE_SIZE_RATIO = 0.75
