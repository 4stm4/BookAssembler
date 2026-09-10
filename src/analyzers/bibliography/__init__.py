"""
BibliographyDetectorAnalyzer — find "References" / "Bibliography" /
«Литература» containers and promote their ParagraphBlock children to
BibEntryBlock (KRM_ENTITIES_MAP P1.6).

The container itself is marked with semantic_type='bibliography' so
downstream consumers (assembler, chunker, KG) can special-case it.
"""

from src.analyzers.bibliography.analyzer import BibliographyDetectorAnalyzer

__all__ = [
    "BibliographyDetectorAnalyzer",
]
