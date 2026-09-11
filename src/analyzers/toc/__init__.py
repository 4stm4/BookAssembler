"""toc — table of contents as an owned entity.

Detection reads the contents pages' geometry (layout.py): an entry is a row
that points to a page, whatever it is drawn with — dotted leaders, a wide
gap, one column or two. TocAnalyzer runs before the heading tree exists;
TocLinkAnalyzer links the entries to it afterwards.
"""

from src.analyzers.toc.rules import (
    is_toc_heading,
    split_number,
    split_trailing_page,
    strip_leaders,
)
from src.analyzers.toc.analyzer import TocAnalyzer
from src.analyzers.toc.linker import TocLinkAnalyzer

__all__ = [
    "TocAnalyzer",
    "TocLinkAnalyzer",
    "is_toc_heading",
    "split_number",
    "split_trailing_page",
    "strip_leaders",
]
