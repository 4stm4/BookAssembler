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
from src.analyzers.algorithm import AlgorithmDetectorAnalyzer
from src.analyzers.bibliography import BibliographyDetectorAnalyzer
from src.analyzers.block_classifier import BlockClassifierAnalyzer
from src.analyzers.toc import TocAnalyzer
from src.analyzers.callout import CalloutDetectorAnalyzer
from src.analyzers.caption import CaptionAnalyzer
from src.analyzers.citation import CitationLinkerAnalyzer
from src.analyzers.definition import DefinitionDetectorAnalyzer
from src.analyzers.diagram import DiagramDetectorAnalyzer
from src.analyzers.entity import EntityExtractorAnalyzer
from src.analyzers.ephemera import EphemeraDetectorAnalyzer
from src.analyzers.font_stats import FontStatsAnalyzer
from src.analyzers.footnote import FootnoteDetectorAnalyzer
from src.analyzers.formula import FormulaDetectorAnalyzer
from src.analyzers.llm_refinement import LLMRefinementAnalyzer
from src.analyzers.heading import HeadingAnalyzer
from src.analyzers.index import IndexDetectorAnalyzer
from src.analyzers.list import ListDetectorAnalyzer
from src.analyzers.normalization import NormalizationAnalyzer
from src.analyzers.notebook_outputs import NotebookOutputAnalyzer
from src.analyzers.ocr import OCRAnalyzer
from src.analyzers.page_agent import PageAgentAnalyzer
from src.analyzers.pipeline import PipelineRunner
from src.analyzers.proper_noun import ProperNounExtractorAnalyzer
from src.analyzers.reading_order import ReadingOrderAnalyzer
from src.analyzers.table import TableDetectorAnalyzer
from src.analyzers.theorem import TheoremDetectorAnalyzer
from src.analyzers.title_page import TitlePageAnalyzer
from src.analyzers.vision_fallback import VisionFallbackAnalyzer

def create_default_pipeline() -> List[BaseAnalyzer]:
    return [
        NormalizationAnalyzer(),
        # Recovers text on pages with no text layer before anything tries to
        # read it — every detector downstream works on text (RFC 0008 §75).
        OCRAnalyzer(),
        # No-op unless the document came from a notebook (RFC 0008 §3.4).
        NotebookOutputAnalyzer(),
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
        # Owns TOC detection (was inside BlockClassifier): a "CONTENTS"
        # heading over a section list is a TOC too, not only the
        # dotted-leader form.
        TocAnalyzer(),
        BlockClassifierAnalyzer(),
        LLMRefinementAnalyzer(),
        VisionFallbackAnalyzer(),
        EntityExtractorAnalyzer(),
        ProperNounExtractorAnalyzer(),
        CitationLinkerAnalyzer(),
        # Last: reading order is built over the final tree. Running it early
        # (it used to be step 3) linked the pre-restructure leaves, and every
        # detector that then wrapped a paragraph into a list / callout / table
        # or promoted it to a container left the MAIN_FLOW edges pointing at
        # nodes the chunker no longer sees (RFC 0007 §5). No analyzer consumes
        # the reading graph mid-pipeline, so this is safe to defer.
        ReadingOrderAnalyzer(),
    ]

__all__ = [
    "AlgorithmDetectorAnalyzer",
    "AnalyzerManifest",
    "BaseAnalyzer",
    "BibliographyDetectorAnalyzer",
    "BlockClassifierAnalyzer",
    "TocAnalyzer",
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
    "NotebookOutputAnalyzer",
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
