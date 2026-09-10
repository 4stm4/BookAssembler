"""proper_noun: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from src.graph.knowledge_graph import EntityType, KGEntityNode, KnowledgeGraph, RelationType

# Person: "A. B. Surname", "A.B. Surname", "Firstname Surname" (capitalized)
_PERSON_RE = re.compile(
    r"\b(?:"
    r"(?:[A-ZА-ЯЁ]\.[\s]?){1,3}[A-ZА-ЯЁ][a-zа-яё]{2,}"  # A. B. Surname
    r"|[A-ZА-ЯЁ][a-zа-яё]{2,}\s+[A-ZА-ЯЁ][a-zа-яё]{2,}"  # Firstname Surname
    r")\b"
)

# Organization: uppercase abbreviations (2-6 letters) or words ending with Inc/Corp/Ltd/ООО/ОАО
_ORG_RE = re.compile(
    r"\b(?:"
    r"[A-ZА-ЯЁ]{2,6}"  # DEC, IBM, IEEE
    r"|[A-ZА-ЯЁ][a-zа-яё]+(?:\s+(?:Inc|Corp|Ltd|LLC|Co|GmbH|ООО|ОАО|ЗАО))\b"
    r")"
)

# Product: alphanumeric model names with dash/numbers
_PRODUCT_RE = re.compile(
    r"\b(?:"
    r"PDP-\d{1,2}(?:/\d{1,2})?"  # PDP-11, PDP-11/70
    r"|MC\d{4,5}"  # MC68000
    r"|VAX-\d+"  # VAX-11
    r"|[A-Z]{2,4}-\d{3,6}[A-Z]?"  # ARM-926, Z80
    r"|(?:Intel|AMD|Motorola|ARM)\s+\w+"
    r")\b"
)

# Date: YYYY, DD.MM.YYYY, Month YYYY
_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[./]\d{1,2}[./]\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)

# Version: vN.N.N, version N.N
_VERSION_RE = re.compile(
    r"\b(?:v|version\s+|версия\s+)\d+(?:\.\d+){0,3}\b",
    re.IGNORECASE,
)

_PATTERNS: List[Tuple[re.Pattern, EntityType]] = [
    (_PRODUCT_RE, EntityType.PRODUCT),
    (_VERSION_RE, EntityType.VERSION),
    (_DATE_RE, EntityType.DATE),
    (_PERSON_RE, EntityType.PERSON),
]
