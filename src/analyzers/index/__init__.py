"""
IndexDetectorAnalyzer — detect back-of-book index entries.

Finds containers titled Index/Указатель/Предметный указатель, then promotes
children matching "Term, p1, p2-p3" to IndexEntryBlock.
"""

from src.analyzers.index.signals import _INDEX_ENTRY_RE, _INDEX_TITLE_RE
from src.analyzers.index.rules import _parse_page_refs
from src.analyzers.index.analyzer import IndexDetectorAnalyzer

__all__ = [
    "IndexDetectorAnalyzer",
    "_INDEX_ENTRY_RE",
    "_INDEX_TITLE_RE",
    "_parse_page_refs",
]
