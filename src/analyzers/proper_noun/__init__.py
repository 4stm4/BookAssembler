"""
ProperNounExtractorAnalyzer — extract named entities (Person, Organization,
Product, Date, Version) from paragraph text using regex heuristics.

Creates KGEntityNode entries and MENTIONS_ENTITY edges from block→entity.
Deduplicates by canonical_name within the same document run.
"""

from src.analyzers.proper_noun.analyzer import ProperNounExtractorAnalyzer

__all__ = [
    "ProperNounExtractorAnalyzer",
]
