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
from src.analyzers.algorithm_detector import AlgorithmDetectorAnalyzer
from src.analyzers.bibliography_detector import BibliographyDetectorAnalyzer
from src.analyzers.block_classifier import BlockClassifierAnalyzer
from src.analyzers.callout_detector import CalloutDetectorAnalyzer
from src.analyzers.caption_analyzer import CaptionAnalyzer
from src.analyzers.citation_linker import CitationLinkerAnalyzer
from src.analyzers.definition_detector import DefinitionDetectorAnalyzer
from src.analyzers.diagram_detector import DiagramDetectorAnalyzer
from src.analyzers.entity_extractor import EntityExtractorAnalyzer
from src.analyzers.ephemera_detector import EphemeraDetectorAnalyzer
from src.analyzers.font_stats import FontStatsAnalyzer
from src.analyzers.footnote_detector import FootnoteDetectorAnalyzer
from src.analyzers.formula_detector import FormulaDetectorAnalyzer
from src.analyzers.llm_refinement import LLMRefinementAnalyzer
from src.analyzers.heading import HeadingAnalyzer
from src.analyzers.index_detector import IndexDetectorAnalyzer
from src.analyzers.list_detector import ListDetectorAnalyzer
from src.analyzers.normalization import NormalizationAnalyzer
from src.analyzers.ocr import OCRAnalyzer
from src.analyzers.page_agent import PageAgentAnalyzer
from src.analyzers.pipeline import PipelineRunner
from src.analyzers.proper_noun_extractor import ProperNounExtractorAnalyzer
from src.analyzers.reading_order import ReadingOrderAnalyzer
from src.analyzers.table_detector import TableDetectorAnalyzer
from src.analyzers.theorem_detector import TheoremDetectorAnalyzer
from src.analyzers.title_page import TitlePageAnalyzer
from src.analyzers.vision_fallback import VisionFallbackAnalyzer


def create_default_pipeline() -> List[BaseAnalyzer]:
    return [
        NormalizationAnalyzer(),
        # Recovers text on pages with no text layer before anything tries to
        # read it — every detector downstream works on text (RFC 0008 §75).
        OCRAnalyzer(),
        ReadingOrderAnalyzer(),
        FontStatsAnalyzer(),
        EphemeraDetectorAnalyzer(),
        DiagramDetectorAnalyzer(),
        HeadingAnalyzer(),
        ListDetectorAnalyzer(),
        FormulaDetectorAnalyzer(),
        TheoremDetectorAnalyzer(),
        DefinitionDetectorAnalyzer(),
        CalloutDetectorAnalyzer(),
        FootnoteDetectorAnalyzer(),
        BibliographyDetectorAnalyzer(),
        AlgorithmDetectorAnalyzer(),
        IndexDetectorAnalyzer(),
        TitlePageAnalyzer(),
        TableDetectorAnalyzer(),
        # Ask a vision agent about table-like pages TableDetector missed
        # (calls the "table"-role agent; no-op if none is reachable).
        PageAgentAnalyzer(),
        CaptionAnalyzer(),
        BlockClassifierAnalyzer(),
        LLMRefinementAnalyzer(),
        VisionFallbackAnalyzer(),
        EntityExtractorAnalyzer(),
        ProperNounExtractorAnalyzer(),
        CitationLinkerAnalyzer(),
    ]


__all__ = [
    "AlgorithmDetectorAnalyzer",
    "AnalyzerManifest",
    "BaseAnalyzer",
    "BibliographyDetectorAnalyzer",
    "BlockClassifierAnalyzer",
    "CalloutDetectorAnalyzer",
    "CaptionAnalyzer",
    "CitationLinkerAnalyzer",
    "DefinitionDetectorAnalyzer",
    "EntityExtractorAnalyzer",
    "EphemeraDetectorAnalyzer",
    "FontStatsAnalyzer",
    "FootnoteDetectorAnalyzer",
    "FormulaDetectorAnalyzer",
    "HeadingAnalyzer",
    "IndexDetectorAnalyzer",
    "KGPermission",
    "LLMRefinementAnalyzer",
    "ListDetectorAnalyzer",
    "KRMPermission",
    "NormalizationAnalyzer",
    "PipelineRunner",
    "ProperNounExtractorAnalyzer",
    "RGPermission",
    "ReadingOrderAnalyzer",
    "SecurityViolationError",
    "TableDetectorAnalyzer",
    "TheoremDetectorAnalyzer",
    "TitlePageAnalyzer",
    "VisionFallbackAnalyzer",
    "create_default_pipeline",
]
