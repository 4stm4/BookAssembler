"""
DiagramDetectorAnalyzer — finds the figures drawn on scanned pages.

A scanned figure (a block diagram, a circuit, a timing diagram) arrives as
its labels - short lines of text (Instruction, Datum, Register, EA*, …)
scattered over a region of the page - its lines and arrows living only on
the page's raster. On a page read line by line the figure is found by
those strokes themselves (ink.py): ink far longer than the text's letters
that is no rule, no table's frame and no mark on the text - whether a
caption stands by it or not. Elsewhere it is told by its caption and the
cluster of short labels by it. Either way it becomes one DiagramBlock that
references the page region and keeps every label, so the diagram can be
reconstructed from the scan (RFC 0002/0008 §5.2: detection is analysis,
not adapter work; RFC 0001 §2.4: absorbed labels are tombstoned, never
deleted - a line taken out of a block that keeps its other lines lives on
in the figure's labels).
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
