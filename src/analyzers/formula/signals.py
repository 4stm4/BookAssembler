"""formula: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re

_MATH_FONT_HINTS = (
    "cmmi", "cmsy", "cmex", "msam", "msbm", "stix", "symbol", "math",
    "mtmi", "mtsy", "mtex", "asana", "esint", "yhmath",
)

_MATH_CHARS = set(
    "∫∑∏∐√∞±∓×÷≠≈≤≥≪≫∈∉⊂⊆⊃⊇∪∩∀∃∄∇∂ℝℤℕℚℂ∆Ω"
    "αβγδεζηθικλμνξοπρστυφχψω"
    "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
    "→←↔⇒⇐⇔≡≺≻⊕⊗⊥∠"
)

_FORMULA_NUMBER_RE = re.compile(r"[\(\[]\s*([\d.]+)\s*[\)\]]\s*$")
