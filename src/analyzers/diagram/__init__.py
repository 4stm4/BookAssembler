"""
DiagramDetectorAnalyzer — detects schematic diagrams on scanned pages.

Scanned figures (block diagrams, flowcharts) arrive as many short text labels
(Instruction, Datum, Register, EA*, …) scattered over a page region, with the
lines/arrows living only on the page raster. This analyzer clusters those short
labels into a single DiagramBlock that references the page region, so the diagram
can be reconstructed from the scan with every label preserved (RFC 0002/0008 §5.2:
detection is analysis, not adapter work; RFC 0001 §2.4: absorbed labels are
tombstoned, never deleted).
"""

from src.analyzers.diagram.signals import LEFT_PAD, MAX_LABEL_WIDTH, MAX_LABEL_WORDS, MIN_LABELS, PAD, RIGHT_PAD, log
from src.analyzers.diagram.analyzer import DiagramDetectorAnalyzer

__all__ = [
    "DiagramDetectorAnalyzer",
    "LEFT_PAD",
    "MAX_LABEL_WIDTH",
    "MAX_LABEL_WORDS",
    "MIN_LABELS",
    "PAD",
    "RIGHT_PAD",
    "log",
]
