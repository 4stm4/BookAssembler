"""
Corpus & Benchmark Suite for Knowledge Assembly Engine (KAE).

Provides metrics calculation and benchmark runner according to RFC 0009
(docs/architecture/0009-benchmark.md).
"""

from src.benchmark.metrics import (
    compute_edit_distance,
    compute_link_f1,
    compute_teds,
    compute_wer,
)
from src.benchmark.runner import (
    BenchmarkReport,
    BenchmarkRunner,
    RegressionError,
)
from src.benchmark.taxonomy import (
    ErrorCategory,
    QualityTaxonomyReport,
    TaxonomyAnalyzer,
    TaxonomyErrorItem,
)

__all__ = [
    "BenchmarkReport",
    "BenchmarkRunner",
    "ErrorCategory",
    "QualityTaxonomyReport",
    "RegressionError",
    "TaxonomyAnalyzer",
    "TaxonomyErrorItem",
    "compute_edit_distance",
    "compute_link_f1",
    "compute_teds",
    "compute_wer",
]
