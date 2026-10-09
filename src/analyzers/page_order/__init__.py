"""page_order — a scanned page's blocks in the order it is read.

PageOrderAnalyzer orders the blocks of each scanned page as a reader
goes through it - its columns one after another, the bands between what
runs across them one under another - before anything builds the
document's structure out of their order (HeadingAnalyzer).
"""

from src.analyzers.page_order.analyzer import PageOrderAnalyzer

__all__ = ["PageOrderAnalyzer"]
