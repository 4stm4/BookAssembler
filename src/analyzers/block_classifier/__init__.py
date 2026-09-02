"""
BlockClassifierAnalyzer — adjusts classification_confidence and detects TOC.

Adaptive TOC detection: finds clusters of short blocks ending with page numbers
on the same pages. No hardcoded patterns — works across different book formats.

Algorithm:
1. For each container, scan ParagraphBlocks for "ends with number" pattern
2. Find runs of 4+ consecutive such blocks on the same or adjacent pages
3. Group runs into ContainerUnit(semantic_type='toc')
4. For remaining ParagraphBlocks, compute classification_confidence from features
"""

from src.analyzers.block_classifier.signals import MAX_TOC_TEXT_LEN, MIN_TOC_RUN
from src.analyzers.block_classifier.analyzer import BlockClassifierAnalyzer

__all__ = [
    "BlockClassifierAnalyzer",
    "MAX_TOC_TEXT_LEN",
    "MIN_TOC_RUN",
]
