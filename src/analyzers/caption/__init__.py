"""
CaptionAnalyzer — detects figure/table/example captions and links them.

Per RFC 0005: READ, TRANSFORM_NODE on KRM; READ, MUTATE_EDGES on RG.
Identifies ParagraphBlocks matching caption patterns (e.g. "Figure 1-5 ASCII code.")
and converts them to CaptionBlock, linking to the nearest target block via caption_id.

Also detects ContainerUnit titles matching "Example N" and sets semantic_type='example'.
"""

from src.analyzers.caption.analyzer import CaptionAnalyzer

__all__ = [
    "CaptionAnalyzer",
]
