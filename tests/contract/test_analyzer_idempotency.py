"""RFC 0014 idempotency: double-run each analyzer → identical AST hash."""
import copy
import hashlib
import json
from typing import Any, Dict, List

import pytest

from src.analyzers import create_default_pipeline
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _para(text: str, page: int, y0: float, conf: float = 0.5) -> ParagraphBlock:
    p = ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            page_or_screen_index=page,
            bounding_box=NormalizedRect(x0=0.1, y0=y0, x1=0.9, y1=y0 + 0.04),
        ),
    )
    p.extraction_confidence = conf
    p.classification_confidence = conf
    return p


def _make_doc() -> KnowledgeDocument:
    """A document that actually activates the detectors.

    Five identical paragraphs made every table/list/formula/callout detector
    idempotent vacuously — they had nothing to detect, so a double run trivially
    matched. Each group below is shaped to trip one detector.
    """
    blocks = []
    y = 0.04

    def add(text: str, page: int = 0, conf: float = 0.5) -> None:
        nonlocal y
        blocks.append(_para(text, page, y, conf))
        y = round(y + 0.05, 4)

    add("Chapter 1  Introduction", conf=0.4)
    add("The quick brown fox jumps over the lazy dog repeatedly.")
    add("A second paragraph of ordinary body text for the classifier.")

    # list
    add("1. first item")
    add("2. second item")
    add("3. third item")

    # table-ish grid: short, numeric, aligned
    add("Year   Count   Total")
    add("1979   12      144")
    add("1980   15      225")
    add("1981   18      324")

    # formula / callout / footnote / bibliography shapes
    add("E = mc^2")
    add("Note: this paragraph is shaped like a callout.")
    add("1. Knuth, D. The Art of Computer Programming. 1968.")
    add("* footnote marker text at the bottom of the page", conf=0.3)

    y = 0.04
    add("Second page text so page-level analyzers see more than one page.", page=1)
    add("Another line of body text on the second page.", page=1)

    container = ContainerUnit(title="Chapter 1", level=1, children=blocks)
    return KnowledgeDocument(
        title="Test Doc",
        source_uri="file://idempotency.pdf",
        root_containers=[container],
    )


def _ast_hash(doc: KnowledgeDocument) -> str:
    """Produce a deterministic hash of the document's structural content."""

    def _node_dict(node: Any) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": type(node).__name__, "id": node.id}
        if hasattr(node, "is_tombstoned"):
            d["tombstoned"] = node.is_tombstoned
        if hasattr(node, "metadata") and node.metadata:
            d["metadata"] = dict(node.metadata)
        if hasattr(node, "classification_confidence"):
            d["cc"] = round(node.classification_confidence, 6)
        if hasattr(node, "extraction_confidence"):
            d["ec"] = round(node.extraction_confidence, 6)
        if hasattr(node, "children"):
            d["children"] = [_node_dict(c) for c in node.children]
        if hasattr(node, "inlines"):
            d["inlines"] = [
                {"spans": [s.text for s in getattr(il, "spans", [])]}
                for il in (node.inlines or [])
            ]
        if hasattr(node, "rows"):
            d["rows"] = [[getattr(cell, "text", "") for cell in row] for row in (node.rows or [])]
        if hasattr(node, "items"):
            d["items"] = [_node_dict(it) for it in (node.items or [])]
        if hasattr(node, "content") and not hasattr(node, "children"):
            d["content"] = [_node_dict(c) for c in (node.content or [])]
        return d

    tree = {
        "title": doc.title,
        "containers": [_node_dict(c) for c in doc.root_containers],
    }
    raw = json.dumps(tree, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _analyzers_to_test():
    """Every analyzer in the default pipeline.

    Nothing is skipped: the ones that call out to a model are covered by
    stubbing the call (see `stub_llm`), because their idempotency rests on the
    "already refined" guard rather than on what the model answers.
    """
    return list(create_default_pipeline())


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """Answer every LLM/vision call deterministically and offline.

    LLMRefinementAnalyzer was the analyzer the RFC 0014 gap was about, so
    excluding it left the contract unverified. A fixed reply is enough: a second
    run must skip the blocks the first one marked, whatever the reply was.
    """
    from src.analyzers.llm_refinement import analyzer as llm_refinement

    reply = '[{"index": 1, "type": "paragraph", "confidence": 0.8}]'
    monkeypatch.setattr(llm_refinement, "_call_ollama", lambda *a, **k: reply)
    monkeypatch.setattr(
        "src.agents.router.pick", lambda role: (None, None, ""), raising=False
    )


class TestAnalyzerIdempotency:
    @pytest.mark.parametrize(
        "analyzer", _analyzers_to_test(), ids=lambda a: type(a).__name__
    )
    def test_double_run_identical(self, analyzer):
        doc = _make_doc()
        rg = ReadingGraph()
        kg = KnowledgeGraph()

        analyzer.run(doc, rg, kg)
        hash1 = _ast_hash(doc)

        analyzer.run(doc, rg, kg)
        hash2 = _ast_hash(doc)

        assert hash1 == hash2, (
            f"{type(analyzer).__name__} is not idempotent: "
            f"hash changed from {hash1[:16]} to {hash2[:16]}"
        )
