"""
CalloutDetectorAnalyzer — promote ParagraphBlocks that start with a
"Note:"/"Warning:"/"Tip:"/«Внимание»/⚠/ℹ prefix to CalloutBlock so the
assembler can render them inside a framed admonition environment
(KRM_ENTITIES_MAP P1.4).

The whole prefix ("Note:", "Warning —", "⚠ Внимание.") is stripped into
CalloutBlock.label; the trailing text becomes the first paragraph of
content. Identity of the source block is preserved (RFC 0001 §2.3).
"""

from src.analyzers.callout.analyzer import CalloutDetectorAnalyzer

__all__ = [
    "CalloutDetectorAnalyzer",
]
