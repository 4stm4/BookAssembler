"""Graded nDCG and dataset provenance (RFC 0018 §2.3, §3)."""

import pytest

from src.ai_layer.models import AIContextChunk, ChunkBreadcrumbs
from src.eval.retrieval import DatasetGenerator, RetrievalEvaluator


def test_ndcg_grades_a_partial_match_below_the_right_one() -> None:
    """With graded relevance, ranking the merely-related chunk first costs score."""
    grades = {"chunk_exact": 3.0, "chunk_related": 1.0}

    best_first = RetrievalEvaluator.compute_ndcg(
        ["chunk_exact", "chunk_related"], grades, k=2
    )
    related_first = RetrievalEvaluator.compute_ndcg(
        ["chunk_related", "chunk_exact"], grades, k=2
    )

    assert best_first == pytest.approx(1.0)
    assert related_first < best_first


def test_binary_relevance_still_accepted() -> None:
    assert RetrievalEvaluator.compute_ndcg(["a", "b"], ["a", "b"], k=2) == pytest.approx(1.0)
    assert RetrievalEvaluator.compute_ndcg(["x"], ["a"], k=1) == 0.0


def test_grade_zero_contributes_nothing() -> None:
    assert RetrievalEvaluator.compute_ndcg(["a"], {"a": 0.0}, k=1) == 0.0


def _chunk() -> AIContextChunk:
    return AIContextChunk(
        chunk_id="chunk-1",
        source_krm_ids=["krm-1"],
        text_content="MOV R0, R1",
        chunk_type="instruction",
        breadcrumbs=ChunkBreadcrumbs(document_title="PDP-11 Handbook"),
        source_locations=[
            {"krm_id": "krm-1", "page": 42, "bbox": [0.1, 0.2, 0.3, 0.4]}
        ],
    )


def test_datasets_carry_page_and_bbox() -> None:
    chunks = [_chunk()]

    instruction = DatasetGenerator.generate_instruction_dataset(chunks)[0]
    qa = DatasetGenerator.generate_qa_dataset(chunks)[0]

    for item in (instruction, qa):
        location = item["provenance_info"]["source_locations"][0]
        assert location["page"] == 42
        assert location["bbox"] == [0.1, 0.2, 0.3, 0.4]
        assert location["krm_id"] == "krm-1"
