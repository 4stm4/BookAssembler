"""
Unit tests for Corpus & Benchmark Suite (RFC 0009).

Tests verify:
1. compute_edit_distance, compute_wer, compute_teds, and compute_link_f1 calculations.
2. BenchmarkRunner evaluation of samples against expected golden truth files.
3. Raising of RegressionError when strict=True and metrics fall below thresholds.
"""

import contextlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

try:
    import pytest
except ImportError:
    @contextlib.contextmanager
    def _pytest_raises_fallback(expected_exception: type[BaseException], match: str | None = None) -> Any:
        try:
            yield
        except expected_exception as e:
            if match and not re.search(match, str(e)):
                raise AssertionError(f"Pattern '{match}' not found in exception message: '{e}'")
        else:
            raise AssertionError(f"Expected exception {expected_exception} was not raised")

    class _PytestShim:
        raises = staticmethod(_pytest_raises_fallback)

    pytest = _PytestShim()  # type: ignore[assignment]


from src.benchmark import (
    BenchmarkReport,
    BenchmarkRunner,
    RegressionError,
    compute_edit_distance,
    compute_link_f1,
    compute_teds,
    compute_wer,
)
from src.graph.knowledge_graph import (
    EntityType,
    KGEdge,
    KGEntityNode,
    KnowledgeGraph,
    RelationType,
)
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)


def test_compute_wer() -> None:
    """Verify compute_wer for exact match, word modifications, and empty strings."""
    ref = "The quick brown fox jumps over the lazy dog"
    hyp_exact = "The quick brown fox jumps over the lazy dog"
    hyp_error = "The fast brown fox jumps over a lazy dog"

    assert compute_wer(ref, hyp_exact) == 0.0
    wer_err = compute_wer(ref, hyp_error)
    assert wer_err > 0.0
    assert abs(wer_err - (2.0 / 9.0)) < 1e-6

    # Empty inputs
    assert compute_wer("", "") == 0.0
    assert compute_wer("", "some text") == 1.0


def test_compute_edit_distance_and_teds() -> None:
    """Verify sequence edit distance and table TEDS metric calculations."""
    seq1 = ["row", "col1", "col2"]
    seq2 = ["row", "col1", "col2"]
    seq3 = ["row", "col1", "col3"]

    assert compute_edit_distance(seq1, seq2) == 0
    assert compute_edit_distance(seq1, seq3) == 1

    table_expected = {"grid": [["Header 1", "Header 2"], ["Data 1", "Data 2"]]}
    table_exact = {"grid": [["Header 1", "Header 2"], ["Data 1", "Data 2"]]}
    table_degraded = {"grid": [["Header 1", "Header 2"], ["Data 1", "Bad Data"]]}

    assert compute_teds(table_expected, table_exact) == 1.0
    teds_deg = compute_teds(table_expected, table_degraded)
    assert 0.0 < teds_deg < 1.0


def test_compute_link_f1() -> None:
    """Verify compute_link_f1 for exact, partial, and empty graph edge matching."""
    expected = [
        {"source_id": "ent1", "target_id": "ent2", "relation_type": "CONTAINS"},
        {"source_id": "ent2", "target_id": "ent3", "relation_type": "REFERENCES"},
    ]

    extracted_exact = [
        {"source_id": "ent1", "target_id": "ent2", "relation_type": "CONTAINS"},
        {"source_id": "ent2", "target_id": "ent3", "relation_type": "REFERENCES"},
    ]

    extracted_partial = [
        {"source_id": "ent1", "target_id": "ent2", "relation_type": "CONTAINS"},
        {"source_id": "ent2", "target_id": "ent4", "relation_type": "REFERENCES"},
    ]

    # Exact match
    res_exact = compute_link_f1(expected, extracted_exact)
    assert res_exact["precision"] == 1.0
    assert res_exact["recall"] == 1.0
    assert res_exact["f1"] == 1.0

    # Partial match
    res_partial = compute_link_f1(expected, extracted_partial)
    assert res_partial["precision"] == 0.5
    assert res_partial["recall"] == 0.5
    assert res_partial["f1"] == 0.5

    # Empty edge sets
    res_empty = compute_link_f1([], [])
    assert res_empty["f1"] == 1.0


def test_benchmark_runner_and_regression_error() -> None:
    """Verify BenchmarkRunner evaluating golden sample and throwing RegressionError on failure."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        corpus_path = Path(tmp_dir)
        sample_path = corpus_path / "sample_doc"
        expected_path = sample_path / "expected"
        expected_path.mkdir(parents=True)

        # Write golden truth files
        expected_text = "Knowledge Assembly Engine Architecture Overview Col1 | Col2 Val1 | Val2"
        (expected_path / "expected_text.txt").write_text(expected_text, encoding="utf-8")
        
        table_data = {"grid": [["Col1", "Col2"], ["Val1", "Val2"]]}
        (expected_path / "expected_table.json").write_text(json.dumps(table_data), encoding="utf-8")

        kg_data = {
            "edges": [
                {"source_id": "node1", "target_id": "node2", "relation_type": "part_of_arch"}
            ]
        }
        (expected_path / "knowledge_graph.json").write_text(json.dumps(kg_data), encoding="utf-8")

        # Create matching Document and KnowledgeGraph
        doc = KnowledgeDocument(title="", source_uri="/docs/overview.md")
        root = ContainerUnit(title="", level=1)
        para = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Knowledge Assembly Engine Architecture Overview")])])
        
        from src.krm.models import TableBlock, TableCell
        cell1 = TableCell(content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Col1")])])])
        cell2 = TableCell(content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Col2")])])])
        cell3 = TableCell(content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Val1")])])])
        cell4 = TableCell(content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Val2")])])])
        table = TableBlock(grid=[[cell1, cell2], [cell3, cell4]])

        root.children.append(para)
        root.children.append(table)
        doc.root_containers.append(root)

        kg = KnowledgeGraph()
        e1 = KGEntityNode(id="node1", name="node1", entity_type=EntityType.CONCEPT_TERM, canonical_name="node1")
        e2 = KGEntityNode(id="node2", name="node2", entity_type=EntityType.CONCEPT_TERM, canonical_name="node2")
        kg.add_entity(e1)
        kg.add_entity(e2)
        kg.add_edge("node1", "node2", RelationType.PART_OF_ARCHITECTURE)

        runner = BenchmarkRunner(corpus_dir=corpus_path)

        # 1. Evaluate sample - should pass
        report = runner.evaluate_sample(sample_path, doc, kg)
        assert report.passed is True
        assert report.wer_score <= 0.05
        assert report.link_f1_score >= 0.90
        assert report.teds_score >= 0.95

        # Run suite strict - should succeed
        reports = runner.run_suite({"sample_doc": (doc, kg)}, strict=True)
        assert len(reports) == 1
        assert reports[0].passed is True

        # 2. Artificially degrade document text to trigger WER regression
        degraded_doc = KnowledgeDocument(title="Wrong Title", source_uri="/docs/overview.md")
        degraded_root = ContainerUnit(title="Unrelated Header", level=1)
        degraded_para = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Completely different corrupted content text")])])
        degraded_root.children.append(degraded_para)
        degraded_doc.root_containers.append(degraded_root)

        degraded_report = runner.evaluate_sample(sample_path, degraded_doc, kg)
        assert degraded_report.passed is False
        assert degraded_report.wer_score > 0.05

        # Strict run with degraded doc must raise RegressionError
        with pytest.raises(RegressionError, match="Benchmark strict regression check failed"):
            runner.run_suite({"sample_doc": (degraded_doc, kg)}, strict=True)
