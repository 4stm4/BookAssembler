"""
OCRAnalyzer — recovers text from pages that have no text layer (RFC 0008 §75).

PdfSourceAdapter marks such pages `needs_ocr=True` and emits an empty
placeholder for each, because there is nothing to extract. Until this analyzer
existed the flag was written and never read: on the corpus in /data/kae/books
that is 238 of 1738 pages, and 19 documents that are scans end to end, which
came out of the pipeline as empty placeholders and nothing else.

This is also the one case where a vision agent is not an optimisation but the
only option — there is no text layer to fall back on, and OCR on the ARM hosts
of this cluster runs in minutes per page.

The placeholder is tombstoned rather than dropped (RFC 0001 §2.4) and the
recovered lines are inserted in its place, each carrying its own box and font
so the assembler can lay the page out positionally (RFC 0021 §5.4). The model
is asked for that geometry directly: a scan has no text layer to take it from,
and without it every line collapses onto the page box and renders stacked at
the top in a default font.
"""

from src.analyzers.ocr.config import OCR_ATTEMPTS, OCR_CONCURRENCY, OCR_DPI, OCR_MAX_DIM, OCR_TIMEOUT
from src.analyzers.ocr.signals import FAILURE_BUDGET_RATIO, MIN_FAILURE_BUDGET, log
from src.analyzers.ocr.analyzer import OCRAnalyzer

__all__ = [
    "FAILURE_BUDGET_RATIO",
    "MIN_FAILURE_BUDGET",
    "OCRAnalyzer",
    "OCR_ATTEMPTS",
    "OCR_CONCURRENCY",
    "OCR_DPI",
    "OCR_MAX_DIM",
    "OCR_TIMEOUT",
    "log",
]
