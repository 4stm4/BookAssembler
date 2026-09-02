"""
ProperNounExtractorAnalyzer — extract named entities (Person, Organization,
Product, Date, Version) from paragraph text using regex heuristics.

Creates KGEntityNode entries and MENTIONS_ENTITY edges from block→entity.
Deduplicates by canonical_name within the same document run.
"""

from src.analyzers.proper_noun.signals import _DATE_RE, _ORG_RE, _PATTERNS, _PERSON_RE, _PRODUCT_RE, _VERSION_RE
from src.analyzers.proper_noun.analyzer import ProperNounExtractorAnalyzer

__all__ = [
    "ProperNounExtractorAnalyzer",
    "_DATE_RE",
    "_ORG_RE",
    "_PATTERNS",
    "_PERSON_RE",
    "_PRODUCT_RE",
    "_VERSION_RE",
]
