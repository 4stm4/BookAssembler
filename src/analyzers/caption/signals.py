"""caption: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_CAPTION_RE = re.compile(
    r"^(Figure|Fig\.|Table|Example|Пример|Таблица|Рис\.)\s+"
    r"(\d+[-–.]\d+|\d+)\s*(.*)",
    re.IGNORECASE,
)

_EXAMPLE_HEADING_RE = re.compile(
    r"^Example\s+(\d+[-–.]\d+|\d+)",
    re.IGNORECASE,
)

_TARGET_TYPE_MAP = {
    "figure": "figure",
    "fig.": "figure",
    "рис.": "figure",
    "table": "table",
    "таблица": "table",
    "example": "example",
    "пример": "example",
}
