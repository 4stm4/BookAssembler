"""register — a register drawn as a framed row of bits.

RegisterAnalyzer reads, off a page's pixels, the frames whose cells are
marked off by ticks - an instruction's encoding in a CPU manual - and sets
each as a table of its bits.
"""

from src.analyzers.register.analyzer import RegisterAnalyzer

__all__ = ["RegisterAnalyzer"]
