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
from src.analyzers.bibliography_detector import BibliographyDetectorAnalyzer
from src.analyzers.block_classifier import BlockClassifierAnalyzer
from src.analyzers.callout_detector import CalloutDetectorAnalyzer
from src.analyzers.caption_analyzer import CaptionAnalyzer
from src.analyzers.citation_linker import CitationLinkerAnalyzer
from src.analyzers.definition_detector import DefinitionDetectorAnalyzer
from src.analyzers.diagram_detector import DiagramDetectorAnalyzer
from src.analyzers.entity_extractor import EntityExtractorAnalyzer
from src.analyzers.footnote_detector import FootnoteDetectorAnalyzer
from src.analyzers.formula_detector import FormulaDetectorAnalyzer
from src.analyzers.llm_refinement import LLMRefinementAnalyzer
from src.analyzers.heading import HeadingAnalyzer
from src.analyzers.list_detector import ListDetectorAnalyzer
from src.analyzers.normalization import NormalizationAnalyzer
from src.analyzers.page_agent import PageAgentAnalyzer
from src.analyzers.pipeline import PipelineRunner
from src.analyzers.proper_noun_extractor import ProperNounExtractorAnalyzer
from src.analyzers.reading_order import ReadingOrderAnalyzer
from src.analyzers.table_detector import TableDetectorAnalyzer
from src.analyzers.theorem_detector import TheoremDetectorAnalyzer
from src.analyzers.title_page import TitlePageAnalyzer


def create_default_pipeline() -> List[BaseAnalyzer]:
    return [
        NormalizationAnalyzer(),
        ReadingOrderAnalyzer(),
        DiagramDetectorAnalyzer(),
        HeadingAnalyzer(),
        ListDetectorAnalyzer(),
        FormulaDetectorAnalyzer(),
        TheoremDetectorAnalyzer(),
        DefinitionDetectorAnalyzer(),
        CalloutDetectorAnalyzer(),
        FootnoteDetectorAnalyzer(),
        BibliographyDetectorAnalyzer(),
        TitlePageAnalyzer(),
        TableDetectorAnalyzer(),
        # Ask a vision agent about table-like pages TableDetector missed
        # (calls the "table"-role agent; no-op if none is reachable).
        PageAgentAnalyzer(),
        CaptionAnalyzer(),
        BlockClassifierAnalyzer(),
        LLMRefinementAnalyzer(),
        EntityExtractorAnalyzer(),
        ProperNounExtractorAnalyzer(),
        CitationLinkerAnalyzer(),
    ]


__all__ = [
    "AnalyzerManifest",
    "BaseAnalyzer",
    "BibliographyDetectorAnalyzer",
    "BlockClassifierAnalyzer",
    "CalloutDetectorAnalyzer",
    "CaptionAnalyzer",
    "CitationLinkerAnalyzer",
    "DefinitionDetectorAnalyzer",
    "EntityExtractorAnalyzer",
    "FootnoteDetectorAnalyzer",
    "FormulaDetectorAnalyzer",
    "HeadingAnalyzer",
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
    "create_default_pipeline",
]
