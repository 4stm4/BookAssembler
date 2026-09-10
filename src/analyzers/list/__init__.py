"""
ListDetectorAnalyzer — group consecutive ParagraphBlock items with leading
list markers into ListBlock/ListItemBlock (KRM_ENTITIES_MAP P0.1).

Recognized markers (case-insensitive):
    • ‣ ∙ ◦ ▪ ▫ ■ □ ● ○ * - – —      → list_style="bullet"
    1. 1)                            → list_style="ordered"
    a. a) а. а)                      → list_style="alpha"
    i. iv) IX)                       → list_style="roman"

A group requires ≥2 consecutive items so a single dashed paragraph is not
promoted. The marker is stripped from the first inline's text and preserved
on ListItemBlock.marker for round-trip.
"""

from src.analyzers.list.analyzer import ListDetectorAnalyzer

__all__ = [
    "ListDetectorAnalyzer",
]
