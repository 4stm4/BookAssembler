"""Unit tests for FormulaDetectorAnalyzer (KRM_ENTITIES_MAP P0.3)."""

from typing import List

from src.analyzers.formula import FormulaDetectorAnalyzer
from src.analyzers.formula.rules import _extract_formula_number, _looks_like_formula
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    FormulaBlock,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyleDescriptor,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _para(text: str, font: str = "sans-serif") -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
            style=StyleDescriptor(font_family=font),
        ),
    )


def _doc(children: List) -> KnowledgeDocument:
    return KnowledgeDocument(
        title="t", source_uri="test://",
        root_containers=[ContainerUnit(title="root", level=1, children=list(children))],
    )


def test_looks_like_formula_by_symbols() -> None:
    assert _looks_like_formula("∫ f(x) dx = F(x) + C") is True
    assert _looks_like_formula("α + β = γ") is True
    assert _looks_like_formula("x = a + b") is True  # short algebra
    assert _looks_like_formula("This is a normal paragraph with words.") is False


def test_extract_formula_number() -> None:
    body, n = _extract_formula_number("x = a + b (3.14)")
    assert n == "3.14"
    assert body == "x = a + b"
    body2, n2 = _extract_formula_number("y = 2")
    assert n2 is None
    assert body2 == "y = 2"


def test_promote_math_font_paragraph() -> None:
    doc = _doc([
        _para("ordinary text of the section", font="Times New Roman"),
        _para("x^2 + y^2 = z^2", font="CMMI10"),
    ])
    FormulaDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    kids = doc.root_containers[0].children
    assert isinstance(kids[0], ParagraphBlock)
    assert isinstance(kids[1], FormulaBlock)
    assert kids[1].latex_expression == "x^2 + y^2 = z^2"
    assert kids[1].metadata["needs_vision_ocr"] is True
    assert kids[1].metadata["detector_signal"] == "font"


def test_promote_by_symbol_density() -> None:
    doc = _doc([
        _para("∫ f(x) dx = F(x) + C  (2.1)"),
    ])
    FormulaDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    node = doc.root_containers[0].children[0]
    assert isinstance(node, FormulaBlock)
    assert node.is_numbered is True
    assert node.formula_number == "2.1"


def test_normal_paragraphs_kept_intact() -> None:
    doc = _doc([_para("This is a normal sentence about registers and instructions.")])
    FormulaDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    assert isinstance(doc.root_containers[0].children[0], ParagraphBlock)


def test_tombstoned_paragraph_untouched() -> None:
    p = _para("α = β", font="CMMI10")
    p.is_tombstoned = True
    doc = _doc([p])
    FormulaDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    # tombstoned stays as ParagraphBlock (still tombstoned)
    node = doc.root_containers[0].children[0]
    assert isinstance(node, ParagraphBlock)
    assert node.is_tombstoned is True


def test_identity_preserved() -> None:
    p = _para("x = a + b (1.1)")
    original_id = p.id
    doc = _doc([p])
    FormulaDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    node = doc.root_containers[0].children[0]
    assert isinstance(node, FormulaBlock)
    assert node.id == original_id  # RFC 0001 §2.3
