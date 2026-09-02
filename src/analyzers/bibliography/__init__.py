"""
BibliographyDetectorAnalyzer — find "References" / "Bibliography" /
«Литература» containers and promote their ParagraphBlock children to
BibEntryBlock (KRM_ENTITIES_MAP P1.6).

The container itself is marked with semantic_type='bibliography' so
downstream consumers (assembler, chunker, KG) can special-case it.
"""

from src.analyzers.bibliography.signals import _BIB_TITLES, _NUMBERED_RE, _YEAR_RE
from src.analyzers.bibliography.rules import _fabricate_key, _is_bib_container, _parse_entry
from src.analyzers.bibliography.analyzer import BibliographyDetectorAnalyzer

__all__ = [
    "BibliographyDetectorAnalyzer",
    "_BIB_TITLES",
    "_NUMBERED_RE",
    "_YEAR_RE",
    "_fabricate_key",
    "_is_bib_container",
    "_parse_entry",
]
