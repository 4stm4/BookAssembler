"""
AlgorithmDetectorAnalyzer — detect pseudocode algorithm blocks.

Prefix pattern: "Algorithm N:" / "Алгоритм N:" followed by pseudocode-like
content (indented lines, keywords like if/then/else/while/for/return).
Promotes matching ParagraphBlock to AlgorithmBlock.
"""

from src.analyzers.algorithm.analyzer import AlgorithmDetectorAnalyzer

__all__ = [
    "AlgorithmDetectorAnalyzer",
]
