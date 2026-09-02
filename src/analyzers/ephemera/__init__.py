"""
EphemeraDetectorAnalyzer — detect running headers, footers, and page numbers.

Heuristics:
- Page number: short block (≤5 chars) at page top/bottom (y<0.08 or y>0.92)
  containing only digits or roman numerals.
- Running header/footer: the SAME text at an extreme y position on several
  pages. Repetition is the whole point — a one-off line near the top of a page
  is a page title or a table heading, not a running head, and ephemera are
  dropped from the exported document.
"""

from src.analyzers.ephemera.signals import MIN_REPEAT_PAGES
from src.analyzers.ephemera.analyzer import EphemeraDetectorAnalyzer

__all__ = [
    "EphemeraDetectorAnalyzer",
    "MIN_REPEAT_PAGES",
]
