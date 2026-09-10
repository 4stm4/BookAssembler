"""
IndexDetectorAnalyzer — detect back-of-book index entries.

Finds containers titled Index/Указатель/Предметный указатель, then promotes
children matching "Term, p1, p2-p3" to IndexEntryBlock.
"""

from src.analyzers.index.analyzer import IndexDetectorAnalyzer

__all__ = [
    "IndexDetectorAnalyzer",
]
