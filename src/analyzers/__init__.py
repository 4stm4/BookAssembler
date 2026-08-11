"""
Analyzers package for Knowledge Assembly Engine (KAE).
Provides base analyzer interface, manifest models, permission enums, and pipeline runner.
"""

from typing import List

from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
    RGPermission,
    SecurityViolationError,
)
from src.analyzers.entity_extractor import EntityExtractorAnalyzer
from src.analyzers.heading import HeadingAnalyzer
from src.analyzers.normalization import NormalizationAnalyzer
from src.analyzers.pipeline import PipelineRunner
from src.analyzers.reading_order import ReadingOrderAnalyzer


def create_default_pipeline() -> List[BaseAnalyzer]:
    return [
        NormalizationAnalyzer(),
        ReadingOrderAnalyzer(),
        HeadingAnalyzer(),
        EntityExtractorAnalyzer(),
    ]


__all__ = [
    "AnalyzerManifest",
    "BaseAnalyzer",
    "EntityExtractorAnalyzer",
    "HeadingAnalyzer",
    "KGPermission",
    "KRMPermission",
    "NormalizationAnalyzer",
    "PipelineRunner",
    "RGPermission",
    "ReadingOrderAnalyzer",
    "SecurityViolationError",
    "create_default_pipeline",
]
