"""
Retrieval Evaluation & Dataset Generation Engine for Knowledge Assembly Engine (KAE).

Provides RetrievalEvalMetrics, RetrievalEvaluator, and DatasetGenerator according to RFC 0018.
"""

from src.eval.retrieval import (
    DatasetGenerator,
    RetrievalEvalMetrics,
    RetrievalEvaluator,
)

__all__ = [
    "DatasetGenerator",
    "RetrievalEvalMetrics",
    "RetrievalEvaluator",
]
