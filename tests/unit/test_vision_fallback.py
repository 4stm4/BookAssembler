"""Unit tests for VisionFallbackAnalyzer."""

from unittest.mock import MagicMock, patch
from typing import Any, Dict, List, Optional

import pytest

from src.analyzers.vision_fallback import (
    VisionFallbackAnalyzer,
    _parse_classify_response,
    VISION_CONFIDENCE_THRESHOLD,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    FormulaBlock,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _para(text: str, conf: float = 0.5) -> ParagraphBlock:
    inline = TextLineInline(spans=[StyledTextSpan(text=text)])
    vl = VisualLayout(
        page_or_screen_index=0,
        bounding_box=NormalizedRect(x0=0.1, y0=0.2, x1=0.9, y1=0.3),
    )
    p = ParagraphBlock(inlines=[inline], visual_layout=vl)
    p.extraction_confidence = 0.7
    p.classification_confidence = conf
    return p


def _formula(latex: str = "x^2") -> FormulaBlock:
    vl = VisualLayout(
        page_or_screen_index=0,
        bounding_box=NormalizedRect(x0=0.2, y0=0.4, x1=0.8, y1=0.5),
    )
    f = FormulaBlock(
        latex_expression=latex,
        visual_layout=vl,
        extraction_confidence=0.7,
        classification_confidence=0.6,
    )
    f.metadata = {"needs_vision_ocr": True}
    return f


def _doc(children: list) -> KnowledgeDocument:
    container = ContainerUnit(title="Ch1", level=1, children=children)
    return KnowledgeDocument(
        title="Test", source_uri="nonexistent.pdf", root_containers=[container]
    )


class TestParseClassifyResponse:
    def test_valid_response(self):
        t, c = _parse_classify_response("formula\n0.85")
        assert t == "formula"
        assert c == 0.85

    def test_type_only(self):
        t, c = _parse_classify_response("table")
        assert t == "table"
        assert c == 0.7

    def test_unknown_type(self):
        t, c = _parse_classify_response("something_unknown\n0.9")
        assert t is None

    def test_none_input(self):
        t, c = _parse_classify_response(None)
        assert t is None

    def test_clamps_confidence(self):
        t, c = _parse_classify_response("paragraph\n1.5")
        assert c == 0.95

    def test_toc_maps(self):
        t, c = _parse_classify_response("toc\n0.8")
        assert t == "toc_entry"


class TestVisionFallbackAnalyzer:
    def test_noop_when_no_vision(self):
        analyzer = VisionFallbackAnalyzer()
        doc = _doc([_para("test", conf=0.3)])
        rg, kg = ReadingGraph(), KnowledgeGraph()

        with patch.object(analyzer, "_ensure_router", return_value=None):
            analyzer.run(doc, rg, kg)

        block = doc.root_containers[0].children[0]
        assert block.classification_confidence == 0.3

    def test_skips_high_confidence_blocks(self):
        analyzer = VisionFallbackAnalyzer()
        doc = _doc([_para("test", conf=0.9)])
        rg, kg = ReadingGraph(), KnowledgeGraph()

        formulas: list = []
        low_conf: list = []
        analyzer._collect_targets(doc.root_containers, formulas, low_conf)
        assert len(formulas) == 0
        assert len(low_conf) == 0

    def test_collects_low_confidence_blocks(self):
        analyzer = VisionFallbackAnalyzer()
        doc = _doc([
            _para("good text", conf=0.9),
            _para("ambiguous", conf=0.3),
            _para("unclear", conf=0.4),
        ])

        formulas: list = []
        low_conf: list = []
        analyzer._collect_targets(doc.root_containers, formulas, low_conf)
        assert len(low_conf) == 2

    def test_collects_formulas_needing_ocr(self):
        analyzer = VisionFallbackAnalyzer()
        f = _formula()
        doc = _doc([f])

        formulas: list = []
        low_conf: list = []
        analyzer._collect_targets(doc.root_containers, formulas, low_conf)
        assert len(formulas) == 1
        assert formulas[0] is f

    def test_skips_tombstoned(self):
        analyzer = VisionFallbackAnalyzer()
        p = _para("test", conf=0.2)
        p.is_tombstoned = True
        doc = _doc([p])

        formulas: list = []
        low_conf: list = []
        analyzer._collect_targets(doc.root_containers, formulas, low_conf)
        assert len(low_conf) == 0

    @patch("src.analyzers.vision_fallback.analyzer.vision_generate")
    @patch("src.analyzers.vision_fallback.analyzer._page_crop_b64")
    def test_formula_ocr_updates_latex(self, mock_crop, mock_vision):
        mock_crop.return_value = "base64data"
        mock_vision.return_value = "\\frac{a}{b} + c^2"

        analyzer = VisionFallbackAnalyzer()
        f = _formula("raw text")
        doc = _doc([f])
        rg, kg = ReadingGraph(), KnowledgeGraph()

        mock_router = MagicMock()
        mock_router.vision_available = True
        mock_router.route.return_value = {"host": "http://test:11434", "model": "llava:7b"}

        with patch.object(analyzer, "_ensure_router", return_value=mock_router):
            analyzer.run(doc, rg, kg)

        assert f.latex_expression == "\\frac{a}{b} + c^2"
        assert f.metadata.get("vision_ocr") is True
        assert "needs_vision_ocr" not in f.metadata

    @patch("src.analyzers.vision_fallback.analyzer.vision_generate")
    @patch("src.analyzers.vision_fallback.analyzer._page_crop_b64")
    def test_classify_updates_metadata(self, mock_crop, mock_vision):
        mock_crop.return_value = "base64data"
        mock_vision.return_value = "table\n0.85"

        analyzer = VisionFallbackAnalyzer()
        p = _para("some data", conf=0.3)
        doc = _doc([p])
        rg, kg = ReadingGraph(), KnowledgeGraph()

        mock_router = MagicMock()
        mock_router.vision_available = True
        mock_router.route.return_value = {"host": "http://test:11434", "model": "llava:7b"}

        with patch.object(analyzer, "_ensure_router", return_value=mock_router):
            analyzer.run(doc, rg, kg)

        assert p.metadata["vision_suggested_type"] == "table"
        assert p.metadata["vision_confidence"] == 0.85
        assert p.classification_confidence > 0.3

    @patch("src.analyzers.vision_fallback.analyzer.vision_generate")
    @patch("src.analyzers.vision_fallback.analyzer._page_crop_b64")
    def test_strips_latex_delimiters(self, mock_crop, mock_vision):
        mock_crop.return_value = "base64data"
        mock_vision.return_value = "$\\alpha + \\beta$"

        analyzer = VisionFallbackAnalyzer()
        f = _formula()
        doc = _doc([f])
        rg, kg = ReadingGraph(), KnowledgeGraph()

        mock_router = MagicMock()
        mock_router.vision_available = True
        mock_router.route.return_value = {"host": "http://test:11434", "model": "llava:7b"}

        with patch.object(analyzer, "_ensure_router", return_value=mock_router):
            analyzer.run(doc, rg, kg)

        assert f.latex_expression == "\\alpha + \\beta"
