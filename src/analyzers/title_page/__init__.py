"""
TitlePageAnalyzer — detects title pages and blank pages.

Title page detection:
1. Collect ALL nodes (ParagraphBlock + ContainerUnit headings) from first MAX_SCAN_PAGES
2. Score each page by signals: ALL CAPS, publisher/copyright/ISBN patterns
3. Pages above threshold → replace all their blocks with one TitlePageBlock

Blank page detection:
- ParagraphBlocks with text ≤ 2 chars (e.g. "-", "") → BlankPageBlock
"""

from src.analyzers.title_page.signals import MAX_SCAN_PAGES, MAX_TITLE_BLOCK_LEN, MIN_SCORE, TITLE_MAX_PAGES, _NodeLoc, _RE_COPYRIGHT, _RE_EDITION, _RE_ISBN, _RE_PUBLISHER, _RE_STRONG, _RE_YEAR, log
from src.analyzers.title_page.rules import _extract_metadata, _get_text, _is_mostly_upper, _score_page_blocks
from src.analyzers.title_page.analyzer import TitlePageAnalyzer

__all__ = [
    "MAX_SCAN_PAGES",
    "MAX_TITLE_BLOCK_LEN",
    "MIN_SCORE",
    "TITLE_MAX_PAGES",
    "TitlePageAnalyzer",
    "_NodeLoc",
    "_RE_COPYRIGHT",
    "_RE_EDITION",
    "_RE_ISBN",
    "_RE_PUBLISHER",
    "_RE_STRONG",
    "_RE_YEAR",
    "_extract_metadata",
    "_get_text",
    "_is_mostly_upper",
    "_score_page_blocks",
    "log",
]
