"""
Unit tests for P1 Infrastructure Modules (RFC 0016, RFC 0017, RFC 0018).

Tests:
1. Human-in-the-Loop Manager & Interactive Corrections (RFC 0016)
2. Confidence Calibrator & ECE Error Metrics (RFC 0017)
3. Retrieval Evaluator & Dataset Generator (RFC 0018)
"""

from src.ai_layer.models import AIContextChunk, ChunkBreadcrumbs
from src.calibration.engine import ConfidenceCalibrator
from src.eval.retrieval import DatasetGenerator, RetrievalEvaluator
from src.hitl.manager import CorrectionStatus, HITLManager
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)
from src.provenance.models import ProvenanceTracker


def test_hitl_low_confidence_flagging_and_correction() -> None:
    """
    Test HITL node flagging based on confidence threshold, human edit payload application,
    status transition to APPROVED_BY_HUMAN, and audit step generation in ProvenanceTracker.
    """
    manager = HITLManager()
    tracker = ProvenanceTracker()

    doc = KnowledgeDocument(title="Doc for HITL Test", source_uri="file:///test/doc.pdf")
    root = ContainerUnit(title="Root Container", level=1)

    # High confidence paragraph
    para_high = ParagraphBlock(
        confidence_score=0.95,
        inlines=[TextLineInline(spans=[StyledTextSpan(text="High confidence content")])],
    )
    # Low confidence paragraph
    para_low = ParagraphBlock(
        confidence_score=0.45,
        inlines=[TextLineInline(spans=[StyledTextSpan(text="Low confidence content")])],
    )

    root.children.append(para_high)
    root.children.append(para_low)
    doc.root_containers.append(root)

    # Step 1: Flag low confidence nodes (threshold = 0.70)
    flagged_tasks = manager.flag_low_confidence_nodes(doc, threshold=0.70)
    assert len(flagged_tasks) == 1
    task = flagged_tasks[0]
    assert task.target_krm_id == para_low.id
    assert task.current_confidence == 0.45
    assert task.status == CorrectionStatus.PENDING_HUMAN_REVIEW

    # Step 2: Apply human correction
    reviewer_id = "reviewer_expert_42"
    correction_payload = {
        "metadata": {"human_verified": True, "notes": "Fixed spelling and semantics"},
    }

    manager.apply_human_correction(
        doc=doc,
        task_id=task.task_id,
        correction_payload=correction_payload,
        reviewer_id=reviewer_id,
        tracker=tracker,
    )

    # Verify node confidence updated to 1.0
    assert para_low.confidence_score == 1.0
    assert para_low.metadata["human_verified"] is True

    # Verify task status updated
    updated_task = manager.get_task(task.task_id)
    assert updated_task is not None
    assert updated_task.status == CorrectionStatus.APPROVED_BY_HUMAN
    assert updated_task.reviewer_id == reviewer_id

    # Verify provenance lineage record updated with human step
    lineage = tracker.get_lineage(para_low.id)
    assert lineage is not None
    assert len(lineage.transformation_history) == 1
    step = lineage.transformation_history[0]
    assert step.agent_type == "human"
    assert step.agent_id == reviewer_id
    assert step.confidence_score == 1.0


def test_confidence_calibration_ece_metrics() -> None:
    """
    Test ECE computation and confidence calibration shifts.
    """
    # Artificial predictions and ground truth values
    predictions = [0.1, 0.2, 0.3, 0.4, 0.8, 0.85, 0.9, 0.95]
    ground_truth = [False, False, False, True, True, True, True, True]

    metrics = ConfidenceCalibrator.compute_ece(
        predictions=predictions, ground_truth=ground_truth, num_bins=5
    )

    assert 0.0 <= metrics.ece_score <= 1.0
    assert len(metrics.bin_confidences) == 5
    assert len(metrics.bin_accuracies) == 5

    # Test calibrate_confidence offset logic
    raw_conf = 0.85
    calibrated = ConfidenceCalibrator.calibrate_confidence(raw_conf, ece_offset=0.10)
    assert abs(calibrated - 0.75) < 1e-6

    # Clamping tests
    assert ConfidenceCalibrator.calibrate_confidence(0.05, ece_offset=0.20) == 0.0
    assert ConfidenceCalibrator.calibrate_confidence(0.95, ece_offset=-0.10) == 1.0


def test_retrieval_evaluation_metrics() -> None:
    """
    Test IR metrics: Recall@K, MRR, nDCG@K.
    """
    retrieved = ["doc_A", "doc_B", "doc_C", "doc_D", "doc_E"]
    relevant = ["doc_B", "doc_D", "doc_X"]

    # Recall@3: top 3 retrieved = ['doc_A', 'doc_B', 'doc_C']. Relevant in top 3: ['doc_B'] (1 / 3)
    recall_3 = RetrievalEvaluator.compute_recall_at_k(retrieved, relevant, k=3)
    assert abs(recall_3 - (1.0 / 3.0)) < 1e-6

    # Recall@5: top 5 retrieved contains ['doc_B', 'doc_D'] (2 / 3)
    recall_5 = RetrievalEvaluator.compute_recall_at_k(retrieved, relevant, k=5)
    assert abs(recall_5 - (2.0 / 3.0)) < 1e-6

    # MRR: First relevant item is 'doc_B' at rank 2 -> MRR = 1/2 = 0.5
    mrr = RetrievalEvaluator.compute_mrr(retrieved, relevant)
    assert abs(mrr - 0.5) < 1e-6

    # nDCG@5 evaluation
    eval_metrics = RetrievalEvaluator.evaluate_retrieval(retrieved, relevant, k=5)
    assert abs(eval_metrics.recall_at_k - (2.0 / 3.0)) < 1e-6
    assert abs(eval_metrics.mrr_score - 0.5) < 1e-6
    assert eval_metrics.ndcg_score > 0.0


def test_dataset_generator_instruction_and_qa() -> None:
    """
    Test dataset generator converting AIContextChunk lists to Instruction and QA formats.
    """
    chunk = AIContextChunk(
        chunk_id="chunk_101",
        source_krm_ids=["para_001", "para_002"],
        text_content="Deep Learning Architecture for Transformer Models.",
        contextual_text="[Context: Overview > Section 1] Deep Learning Architecture for Transformer Models.",
        chunk_type="narrative",
        parent_container_id="cont_001",
        metadata={"domain": "ai_research"},
        breadcrumbs=ChunkBreadcrumbs(
            document_title="AI Manual",
            container_path=["Overview", "Section 1"],
            page_numbers=[12],
        ),
    )

    # Test Instruction Dataset Generation
    instr_dataset = DatasetGenerator.generate_instruction_dataset([chunk])
    assert len(instr_dataset) == 1
    item = instr_dataset[0]
    assert item["chunk_id"] == "chunk_101"
    assert "instruction" in item
    assert item["input"] == chunk.contextual_text
    assert item["output"] == chunk.text_content
    assert "provenance_info" in item
    assert item["provenance_info"]["chunk_id"] == "chunk_101"

    # Test QA Dataset Generation
    qa_dataset = DatasetGenerator.generate_qa_dataset([chunk])
    assert len(qa_dataset) == 1
    qa_item = qa_dataset[0]
    assert qa_item["chunk_id"] == "chunk_101"
    assert "question" in qa_item
    assert qa_item["answer"] == chunk.text_content
    assert "provenance_info" in qa_item


if __name__ == "__main__":
    test_hitl_low_confidence_flagging_and_correction()
    test_confidence_calibration_ece_metrics()
    test_retrieval_evaluation_metrics()
    test_dataset_generator_instruction_and_qa()
    print("ALL P1 INFRASTRUCTURE TESTS PASSED!")
