"""Unit tests for FootnoteDetectorAnalyzer (KRM_ENTITIES_MAP P1.5)."""

from typing import List

from src.analyzers.footnote import FootnoteDetectorAnalyzer
from src.analyzers.footnote.rules import _parse_marker
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    FootnoteBlock,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyleDescriptor,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _para(text: str, font_size: float = 12.0, y0: float = 0.10) -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.1, y0, 0.9, y0 + 0.05),
            style=StyleDescriptor(font_size_pt=font_size),
        ),
    )


def _doc(children: List) -> KnowledgeDocument:
    return KnowledgeDocument(
        title="t", source_uri="test://",
        root_containers=[ContainerUnit(title="root", level=1, children=list(children))],
    )


def test_parse_marker_superscript() -> None:
    marker, num, rest = _parse_marker("¹ the note text")
    assert marker == "¹"
    assert num == 1
    assert rest == "the note text"


def test_parse_marker_two_digit_super() -> None:
    _, num, _ = _parse_marker("¹² multi-digit note")
    assert num == 12


def test_parse_marker_digit_with_dot() -> None:
    marker, num, rest = _parse_marker("3. footnote body")
    assert marker == "3."
    assert num == 3


def test_parse_marker_symbol() -> None:
    marker, num, rest = _parse_marker("* another note")
    assert marker == "*"
    assert num is None


def test_promote_small_bottom_paragraph() -> None:
    doc = _doc([
        _para("Body text of the chapter.", font_size=12.0, y0=0.10),
        _para("More body text.", font_size=12.0, y0=0.30),
        _para("¹ this is a footnote.", font_size=8.5, y0=0.92),
    ])
    FootnoteDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    kids = doc.root_containers[0].children
    assert isinstance(kids[0], ParagraphBlock)
    assert isinstance(kids[1], ParagraphBlock)
    fn = kids[2]
    assert isinstance(fn, FootnoteBlock)
    assert fn.footnote_number == 1
    assert "this is a footnote" in fn.text


def test_numbered_body_step_not_a_footnote() -> None:
    """A '1. step' near the top of the page in body font stays a paragraph."""
    doc = _doc([
        _para("Body text.", font_size=12.0, y0=0.10),
        _para("1. First numbered step of a body list.", font_size=12.0, y0=0.20),
    ])
    FootnoteDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    assert all(isinstance(c, ParagraphBlock) for c in doc.root_containers[0].children)


def test_identity_preserved() -> None:
    p = _para("¹ footnote text", font_size=8.5, y0=0.92)
    original_id = p.id
    doc = _doc([_para("body", 12, 0.10), p])
    FootnoteDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    fn = doc.root_containers[0].children[1]
    assert isinstance(fn, FootnoteBlock)
    assert fn.id == original_id


def test_chunker_and_latex_render_footnote() -> None:
    from src.ai_layer.chunker import _extract_text_from_node, _is_atomic_block
    from src.assembler.latex_builder import build_latex

    doc = _doc([_para("body", 12, 0.10), _para("¹ note body", 8.5, 0.92)])
    FootnoteDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    fn = doc.root_containers[0].children[1]
    assert isinstance(fn, FootnoteBlock)
    assert _is_atomic_block(fn)
    assert "note body" in _extract_text_from_node(fn)

    tex = build_latex(doc)
    assert "\\footnotesize" in tex
