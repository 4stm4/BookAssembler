"""callout: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

from typing import Any, Dict, List, Optional, Tuple

# Ordering matters: 'important' before 'note' so 'Important' isn't eaten
# by the shorter alternative.
_LABEL_MAP: List[Tuple[str, str, str]] = [
    # (regex-alternation, kind, severity)
    (r"caution|осторожно", "caution", "critical"),
    (r"warning|внимание|предупреждение", "warning", "warning"),
    (r"danger|опасно", "warning", "critical"),
    (r"important|важно", "important", "warning"),
    (r"tip|подсказка|совет", "tip", "info"),
    (r"note|заметка|замечание|примечание", "note", "info"),
    (r"info|информация", "note", "info"),
]

_ICON_MAP: List[Tuple[str, str, str]] = [
    ("⚠", "warning", "warning"),
    ("❗", "important", "warning"),
    ("‼", "warning", "critical"),
    ("ℹ", "note", "info"),
    ("💡", "tip", "info"),
    ("📝", "note", "info"),
]
