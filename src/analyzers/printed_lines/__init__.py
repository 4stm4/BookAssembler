"""printed_lines — each line of a scanned page, as printed.

PrintedLinesAnalyzer measures, once, every text line of a scanned page
(src/analyzers/printed.py) and records it on its block: what the analyzers
after it judge by (a heading's weight) and what the builder sets the block
by.
"""

from src.analyzers.printed_lines.analyzer import PrintedLinesAnalyzer

__all__ = ["PrintedLinesAnalyzer"]
