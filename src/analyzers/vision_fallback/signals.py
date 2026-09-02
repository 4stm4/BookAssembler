"""vision_fallback: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import logging

log = logging.getLogger(__name__)

_TYPE_MAP = {
    "paragraph": "paragraph",
    "table": "table",
    "formula": "formula",
    "figure": "figure",
    "code": "code",
    "caption": "caption",
    "heading": "heading",
    "list": "list",
    "footnote": "footnote",
    "bibliography": "bibliography",
    "algorithm": "algorithm",
    "index": "index",
    "toc": "toc_entry",
    "blank": "blank",
}
