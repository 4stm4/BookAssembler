"""Unit tests for CalloutDetectorAnalyzer (KRM_ENTITIES_MAP P1.4)."""

from typing import List

from src.analyzers.callout import CalloutDetectorAnalyzer
from src.analyzers.callout.rules import _classify
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    CalloutBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def _para(text: str) -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])]
    )


def _doc(children: List) -> KnowledgeDocument:
    return KnowledgeDocument(
        title="t", source_uri="test://",
        root_containers=[ContainerUnit(title="root", level=1, children=list(children))],
    )


def test_classify_english_labels() -> None:
    assert _classify("Note: this is fine.")[0] == "note"
    assert _classify("Warning: crashes.")[0] == "warning"
    assert _classify("Tip — try flag -q")[0] == "tip"
    assert _classify("Important! read on")[0] == "important"
    assert _classify("Caution: hot.")[0] == "caution"


def test_classify_russian_labels() -> None:
    assert _classify("Внимание! это важно")[0] == "warning"
    assert _classify("Примечание: сноска")[0] == "note"
    assert _classify("Совет: ...")[0] == "tip"


def test_classify_icon_prefix() -> None:
    assert _classify("⚠ Warning: bad")[0] == "warning"
    assert _classify("ℹ Info: about")[0] == "note"
    assert _classify("💡 Tip")[0] == "tip"


def test_classify_ignores_plain_text() -> None:
    assert _classify("This is a normal paragraph.") is None
    assert _classify("Notation: math letters") is None  # 'Notation' not in map


def test_promote_note_paragraph() -> None:
    doc = _doc([_para("Note: keep this small."), _para("regular text")])
    CalloutDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    kids = doc.root_containers[0].children
    assert isinstance(kids[0], CalloutBlock)
    assert kids[0].kind == "note"
    assert kids[0].severity == "info"
    inner = kids[0].content[0]
    assert isinstance(inner, ParagraphBlock)
    assert inner.inlines[0].spans[0].text == "keep this small."
    assert isinstance(kids[1], ParagraphBlock)


def test_identity_preserved() -> None:
    p = _para("Warning: something.")
    original_id = p.id
    doc = _doc([p])
    CalloutDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    cb = doc.root_containers[0].children[0]
    assert isinstance(cb, CalloutBlock)
    assert cb.id == original_id  # RFC 0001 §2.3


def test_latex_and_chunker_render_callout() -> None:
    from src.ai_layer.chunker import _extract_text_from_node, _is_atomic_block
    from src.assembler.latex_builder import build_latex

    doc = _doc([_para("Warning: hot surface.")])
    CalloutDetectorAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
    cb = doc.root_containers[0].children[0]
    assert isinstance(cb, CalloutBlock)
    assert _is_atomic_block(cb)

    text = _extract_text_from_node(cb)
    assert text.startswith("[WARNING]")
    assert "hot surface" in text

    tex = build_latex(doc)
    assert "\\begin{mdframed}" in tex
    assert "\\end{mdframed}" in tex
