"""theorem: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_THEOREM_TYPES = {
    "theorem": "theorem", "теорема": "theorem",
    "lemma": "lemma", "лемма": "lemma",
    "corollary": "corollary", "следствие": "corollary",
    "proposition": "proposition", "утверждение": "proposition",
}

_PROOF_KEYWORDS = {"proof", "доказательство"}

_EXAMPLE_KEYWORDS = {"example", "пример"}

_REMARK_KEYWORDS = {"remark", "замечание", "observation", "наблюдение"}

_THEOREM_RE = re.compile(
    r"^\s*(?P<keyword>" + "|".join(_THEOREM_TYPES.keys()) + r")"
    r"(?:\s+(?P<number>\d+(?:\.\d+)*))?\.?"
    r"(?:\s*\((?P<name>[^)]+)\))?"
    r"\s*[.:—–\-]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_PROOF_RE = re.compile(
    r"^\s*(?P<keyword>" + "|".join(_PROOF_KEYWORDS) + r")"
    r"(?:\s*[.:—–\-])?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_EXAMPLE_RE = re.compile(
    r"^\s*(?P<keyword>" + "|".join(_EXAMPLE_KEYWORDS) + r")"
    r"(?:\s+(?P<number>\d+(?:\.\d+)*))?\.?"
    r"(?:\s*\((?P<name>[^)]+)\))?"
    r"\s*[.:—–\-]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_REMARK_RE = re.compile(
    r"^\s*(?P<keyword>" + "|".join(_REMARK_KEYWORDS) + r")"
    r"(?:\s+(?P<number>\d+(?:\.\d+)*))?\.?"
    r"(?:\s*\((?P<name>[^)]+)\))?"
    r"\s*[.:—–\-]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_PROOF_END_MARKERS = {"□", "∎", "qed", "q.e.d.", "ч.т.д.", "чтд"}
