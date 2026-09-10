"""toc — table of contents as an owned entity.

Detection is not just the dotted-leader form: a "CONTENTS" heading over a
plain section list is a TOC too. See analyzer.py.
"""

from src.analyzers.toc.signals import (
    MAX_TOC_TEXT_LEN,
    MIN_TOC_RUN,
    TOC_PAGE_FRACTION,
)
from src.analyzers.toc.rules import (
    is_toc_entry,
    is_toc_heading,
    parse_entry,
    split_merged_entries,
)
from src.analyzers.toc.analyzer import TocAnalyzer

__all__ = [
    "MAX_TOC_TEXT_LEN",
    "MIN_TOC_RUN",
    "TOC_PAGE_FRACTION",
    "TocAnalyzer",
    "is_toc_entry",
    "is_toc_heading",
    "parse_entry",
    "split_merged_entries",
]
