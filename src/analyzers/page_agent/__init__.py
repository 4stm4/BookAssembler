"""
PageAgentAnalyzer — pipeline stage that pulls a vision agent into extraction.

With a vision agent, every page with content is rendered and sent for
classification: the reply carries the page role (title/toc/table/…), a type for
each listed block, and — when the page is a table — its LaTeX, all in one
request. Absorbed source blocks are tombstoned, never deleted (RFC 0001 §2.4).

Requests for different pages are independent and go out concurrently, though
only a little: the cost is generation on one GPU, not transfer. Replies are
collected without touching the KRM, then applied strictly in page order — the
tree must not depend on which response arrived first (RFC 0009 §5.2).

Without a vision agent only `table`-role recognition is available, and then the
old heuristics still gate which pages are worth a request.
"""

from src.analyzers.page_agent.config import JPEG_MAX_DIM, JPEG_QUALITY, RENDER_DPI, VISION_CONCURRENCY
from src.analyzers.page_agent.signals import FAILURE_BUDGET_RATIO, MIN_BLOCKS, MIN_FAILURE_BUDGET, MIN_NUMERIC_RATIO, MIN_SHORT_RATIO, log
from src.analyzers.page_agent.analyzer import PageAgentAnalyzer

__all__ = [
    "FAILURE_BUDGET_RATIO",
    "JPEG_MAX_DIM",
    "JPEG_QUALITY",
    "MIN_BLOCKS",
    "MIN_FAILURE_BUDGET",
    "MIN_NUMERIC_RATIO",
    "MIN_SHORT_RATIO",
    "PageAgentAnalyzer",
    "RENDER_DPI",
    "VISION_CONCURRENCY",
    "log",
]
