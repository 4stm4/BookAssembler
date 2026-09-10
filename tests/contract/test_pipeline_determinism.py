"""RFC 0009 §5.2: re-running the pipeline on one file yields an identical KRM.

This is the requirement the audit's 0009 entry is about — not that a builder is
a pure function, but that extraction plus analysis, run twice from scratch on
the same source, produces the same tree including node identity.
"""
import hashlib
import io
import json
from typing import Any, Dict

import pytest

from src.analyzers import create_default_pipeline
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph

# Analyzers that reach outside the process. Excluded so the test measures our
# determinism, not a remote model's; each is covered separately.
_EXTERNAL = {
    "LLMRefinementAnalyzer",
    "PageAgentAnalyzer",
    "VisionFallbackAnalyzer",
}


def _krm_hash(doc: Any) -> str:
    """Canonical digest of the tree, ids included — that is the point."""

    def node(n: Any) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": type(n).__name__,
            "id": n.id,
            "tombstoned": getattr(n, "is_tombstoned", False),
            "cc": round(getattr(n, "classification_confidence", 0.0), 6),
            "ec": round(getattr(n, "extraction_confidence", 0.0), 6),
        }
        vl = getattr(n, "visual_layout", None)
        bb = getattr(vl, "bounding_box", None) if vl else None
        if bb:
            d["bbox"] = [round(v, 6) for v in (bb.x0, bb.y0, bb.x1, bb.y1)]
            d["page"] = vl.page_or_screen_index
        if getattr(n, "metadata", None):
            # provenance timestamps are build metadata, not KRM content
            d["metadata"] = {
                k: v for k, v in sorted(n.metadata.items())
                if not k.endswith("_at")
            }
        for attr in ("title", "text", "code_text", "caption_text", "marker"):
            if getattr(n, attr, None):
                d[attr] = getattr(n, attr)
        if getattr(n, "inlines", None):
            d["inlines"] = [
                [s.text for s in getattr(il, "spans", [])]
                for il in n.inlines
            ]
        for attr in ("children", "items", "content"):
            kids = getattr(n, attr, None)
            if kids:
                d[attr] = [node(c) for c in kids]
        return d

    tree = {
        "title": doc.title,
        "containers": [node(c) for c in doc.root_containers],
    }
    return hashlib.sha256(
        json.dumps(tree, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


@pytest.fixture(scope="module")
def pdf_bytes() -> bytes:
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 120), "Chapter 1  Introduction", fontsize=18)
    page.insert_text((72, 160), "The quick brown fox jumps over the lazy dog.")
    page.insert_text((72, 180), "A second paragraph of ordinary body text here.")
    page.insert_text((72, 220), "1. first item")
    page.insert_text((72, 240), "2. second item")
    page.insert_text((72, 280), "Year  Count  Total")
    page.insert_text((72, 300), "1979  12     144")
    page.insert_text((72, 320), "1980  15     225")
    # Caption and front matter: node types the first version of this fixture
    # never produced, which is why non-derived ids on CaptionBlock and
    # TitlePageBlock survived until the real book was diffed.
    page.insert_text((72, 360), "Figure 1-1  Block diagram of the system.")
    page2 = doc.new_page()
    page2.insert_text((72, 120), "TRINITY COLLEGE COMPUTER LABORATORY")
    page2.insert_text((72, 140), "Copyright 1980, University Press Inc.")
    page2.insert_text((72, 160), "ISBN 0-000-00000-0")
    page2.insert_text((72, 200), "More text on a second page for the analyzers.")
    data = doc.tobytes()
    doc.close()
    return data


def _run_pipeline(raw: bytes):
    from src.adapters.pdf_adapter import PdfSourceAdapter

    doc = PdfSourceAdapter().parse(io.BytesIO(raw), "file://determinism.pdf")
    rg, kg = ReadingGraph(), KnowledgeGraph()
    for analyzer in create_default_pipeline():
        if type(analyzer).__name__ in _EXTERNAL:
            continue
        analyzer.run(doc, rg, kg)
    return doc


class TestPipelineDeterminism:
    def test_two_full_runs_produce_identical_krm(self, pdf_bytes):
        first = _krm_hash(_run_pipeline(pdf_bytes))
        second = _krm_hash(_run_pipeline(pdf_bytes))
        assert first == second, (
            "re-running the pipeline on the same file changed the KRM "
            f"({first[:16]} != {second[:16]})"
        )

    def test_three_runs_agree(self, pdf_bytes):
        hashes = {_krm_hash(_run_pipeline(pdf_bytes)) for _ in range(3)}
        assert len(hashes) == 1

    def test_every_node_id_is_derived(self, pdf_bytes):
        """No constructor may fall back to uuid4 for source-derived content.

        Stated over the whole tree rather than per type: a new analyzer that
        forgets to derive or inherit an id fails here without anyone having to
        remember to extend a list. CaptionBlock and TitlePageBlock were exactly
        that kind of miss.
        """
        from src.krm.identity import is_derived

        doc = _run_pipeline(pdf_bytes)
        offenders = []

        def walk(n, depth=0):
            if not is_derived(n.id):
                offenders.append(f"{type(n).__name__}({n.id[:8]})")
            for attr in ("children", "items", "content"):
                for c in getattr(n, attr, None) or []:
                    walk(c, depth + 1)

        for c in doc.root_containers:
            walk(c)

        assert not offenders, (
            "nodes carrying a random uuid4 instead of a derived id: "
            + ", ".join(sorted(set(offenders)))
        )

    def test_different_source_uri_changes_ids(self, pdf_bytes):
        """Identity is keyed on the source, so two documents never collide."""
        from src.adapters.pdf_adapter import PdfSourceAdapter

        a = PdfSourceAdapter().parse(io.BytesIO(pdf_bytes), "file://a.pdf")
        b = PdfSourceAdapter().parse(io.BytesIO(pdf_bytes), "file://b.pdf")
        assert a.root_containers[0].id != b.root_containers[0].id

    def test_hash_is_sensitive_to_content(self, pdf_bytes):
        """Guard against a hash so lossy it would call anything identical."""
        fitz = pytest.importorskip("pymupdf")
        other = fitz.open()
        other.new_page().insert_text((72, 120), "Completely different text")
        other_bytes = other.tobytes()
        other.close()
        assert _krm_hash(_run_pipeline(pdf_bytes)) != \
               _krm_hash(_run_pipeline(other_bytes))
