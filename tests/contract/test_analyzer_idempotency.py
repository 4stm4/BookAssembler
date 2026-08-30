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


def _make_doc() -> KnowledgeDocument:
    """Build a small but representative document for idempotency testing."""
    paras = []
    for i in range(5):
        vl = VisualLayout(
            page_or_screen_index=0,
            bounding_box=NormalizedRect(
                x0=0.1, y0=0.1 + i * 0.15, x1=0.9, y1=0.2 + i * 0.15
            ),
        )
        span = StyledTextSpan(text=f"Paragraph {i} with some content about topic {i}")
        inline = TextLineInline(spans=[span])
        p = ParagraphBlock(inlines=[inline], visual_layout=vl)
        p.extraction_confidence = 0.5
        p.classification_confidence = 0.5
        paras.append(p)

    container = ContainerUnit(title="Chapter 1", level=1, children=paras)
    return KnowledgeDocument(title="Test Doc", root_containers=[container])


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
    """Return analyzers that can run without external services."""
    skip = {
        "LLMRefinementAnalyzer",
        "PageAgentAnalyzer",
    }
    return [a for a in create_default_pipeline() if type(a).__name__ not in skip]


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
