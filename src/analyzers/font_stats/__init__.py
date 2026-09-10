"""
FontStatsAnalyzer — compute document-level font statistics and classify
blocks by font role (body/heading/caption/footnote/code).

Runs early in the pipeline (after Normalization). Collects font fingerprints
(family + size + bold + italic) across all ParagraphBlocks, identifies the
dominant "body" font by frequency, then tags outlier blocks with font_role
metadata that downstream detectors can use as a signal.

Font roles:
- body: most frequent font fingerprint
- heading: same family as body but larger, or bold variant
- caption: smaller than body
- footnote: significantly smaller than body, or at page bottom
- code: monospace font family
- math: math-family font (CMMI, STIX, Symbol, etc.)
"""

from src.analyzers.font_stats.signals import CAPTION_SIZE_RATIO, FOOTNOTE_SIZE_RATIO, HEADING_SIZE_RATIO, log
from src.analyzers.font_stats.rules import FontFingerprint
from src.analyzers.font_stats.analyzer import FontStatsAnalyzer

__all__ = [
    "CAPTION_SIZE_RATIO",
    "FOOTNOTE_SIZE_RATIO",
    "FontFingerprint",
    "FontStatsAnalyzer",
    "HEADING_SIZE_RATIO",
    "log",
]
