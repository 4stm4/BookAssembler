"""scan_noise — letter debris a scan's text layer made of a non-text region.

Judged here, by an analyzer, and tombstoned with a reason — not dropped by
the adapter. See analyzer.py.
"""

from src.analyzers.scan_noise.rules import is_real_word, is_scan_noise
from src.analyzers.scan_noise.analyzer import ScanNoiseAnalyzer

__all__ = [
    "ScanNoiseAnalyzer",
    "is_real_word",
    "is_scan_noise",
]
