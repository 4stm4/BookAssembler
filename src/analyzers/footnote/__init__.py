"""
FootnoteDetectorAnalyzer — promote small-font page-bottom paragraphs
that start with a footnote marker to FootnoteBlock
(KRM_ENTITIES_MAP P1.5).

Signals (paragraph must satisfy all three that apply):
  1. Leading marker: superscript digit (¹²³…), plain digit followed by
     a separator ("1.", "1)"), or a symbol ('*', '†', '‡').
  2. Small font: font_size_pt below body-text mode by ≥ 15 %.
  3. Low y-position: bounding_box.y0 in the bottom 30 % of the page
     (allowing books that print footnotes tighter).

Signals 2 and 3 are best-effort — when the source lacks style/bbox, we
fall back to marker-only. Identity of the source ParagraphBlock is
preserved (RFC 0001 §2.3).
"""

from src.analyzers.footnote.analyzer import FootnoteDetectorAnalyzer

__all__ = [
    "FootnoteDetectorAnalyzer",
]
