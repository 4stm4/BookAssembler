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
from src.analyzers.block_classifier import BlockClassifierAnalyzer
from src.analyzers.caption_analyzer import CaptionAnalyzer
from src.analyzers.diagram_detector import DiagramDetectorAnalyzer
from src.analyzers.entity_extractor import EntityExtractorAnalyzer
from src.analyzers.formula_detector import FormulaDetectorAnalyzer
from src.analyzers.llm_refinement import LLMRefinementAnalyzer
from src.analyzers.heading import HeadingAnalyzer
from src.analyzers.list_detector import ListDetectorAnalyzer
from src.analyzers.normalization import NormalizationAnalyzer
from src.analyzers.page_agent import PageAgentAnalyzer
from src.analyzers.pipeline import PipelineRunner
from src.analyzers.reading_order import ReadingOrderAnalyzer
from src.analyzers.table_detector import TableDetectorAnalyzer
from src.analyzers.title_page import TitlePageAnalyzer


def create_default_pipeline() -> List[BaseAnalyzer]:
    return [
        NormalizationAnalyzer(),
        ReadingOrderAnalyzer(),
        DiagramDetectorAnalyzer(),
        HeadingAnalyzer(),
        ListDetectorAnalyzer(),
        FormulaDetectorAnalyzer(),
        TitlePageAnalyzer(),
        TableDetectorAnalyzer(),
        # Ask a vision agent about table-like pages TableDetector missed
        # (calls the "table"-role agent; no-op if none is reachable).
        PageAgentAnalyzer(),
        CaptionAnalyzer(),
        BlockClassifierAnalyzer(),
        LLMRefinementAnalyzer(),
        EntityExtractorAnalyzer(),
    ]


__all__ = [
    "AnalyzerManifest",
    "BaseAnalyzer",
    "BlockClassifierAnalyzer",
    "CaptionAnalyzer",
    "EntityExtractorAnalyzer",
    "FormulaDetectorAnalyzer",
    "HeadingAnalyzer",
    "KGPermission",
    "LLMRefinementAnalyzer",
    "ListDetectorAnalyzer",
    "KRMPermission",
    "NormalizationAnalyzer",
    "PipelineRunner",
    "RGPermission",
    "ReadingOrderAnalyzer",
    "SecurityViolationError",
    "TableDetectorAnalyzer",
    "TitlePageAnalyzer",
    "create_default_pipeline",
]
