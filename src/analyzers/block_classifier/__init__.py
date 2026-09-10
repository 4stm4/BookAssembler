"""
BlockClassifierAnalyzer — sets a ParagraphBlock's classification confidence
from surface features (length, sentence shape, alpha ratio).

Table-of-contents detection used to live here; it is now src/analyzers/toc.
"""

from src.analyzers.block_classifier.analyzer import BlockClassifierAnalyzer

__all__ = [
    "BlockClassifierAnalyzer",
]
