"""Text desynchronization drift and automatic HITL escalation (RFC 0015 §3.1, §4)."""

import pytest

from src.benchmark.metrics import compute_technical_drift, extract_protected_tokens
from src.hitl.manager import CorrectionStatus, HITLManager
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock


def test_protected_tokens_are_the_ones_translation_must_preserve() -> None:
    tokens = extract_protected_tokens("Load MOV R0, R1 on the PDP-11 at 0x1F")

    assert "MOV" in tokens
    assert "R0" in tokens
    assert "PDP-11" in tokens
    assert "0x1F" in tokens


def test_faithful_translation_has_no_drift() -> None:
    """A correct translation changes every word but keeps the technical tokens."""
    source = "Execute MOV R0, R1 on the PDP-11."
    translated = "Выполните MOV R0, R1 на PDP-11."

    assert compute_technical_drift(source, translated) == 0.0


def test_mangled_mnemonics_register_as_drift() -> None:
    source = "Execute MOV R0, R1 on the PDP-11."
    translated = "Выполните МОВ Р0, Р1 на ПДП-11."

    assert compute_technical_drift(source, translated) > 0.15


def test_prose_without_technical_tokens_never_drifts() -> None:
    assert compute_technical_drift("A short sentence.", "Короткое предложение.") == 0.0


def _doc_with_drift(wer: float) -> KnowledgeDocument:
    paragraph = ParagraphBlock()
    paragraph.metadata = {
        "translations": {
            "RU": {"target_text": "...", "drift": {"protected_token_wer": wer}}
        }
    }
    return KnowledgeDocument(root_containers=[ContainerUnit(children=[paragraph])])


def test_drifted_segment_is_queued_for_a_human() -> None:
    manager = HITLManager()

    flagged = manager.flag_desynchronized_nodes(_doc_with_drift(0.5))

    assert len(flagged) == 1
    assert flagged[0].status is CorrectionStatus.PENDING_HUMAN_REVIEW
    assert flagged[0].suggested_fix["reason"] == "DESYNC_TEXT_DRIFT"
    assert flagged[0].suggested_fix["target_lang"] == "RU"


def test_segment_within_threshold_is_not_queued() -> None:
    assert HITLManager().flag_desynchronized_nodes(_doc_with_drift(0.1)) == []


def test_high_confidence_node_is_still_escalated_on_drift() -> None:
    """Drift escalation is independent of the confidence threshold of RFC 0016."""
    doc = _doc_with_drift(0.9)
    doc.root_containers[0].children[0].confidence_score = 1.0
    manager = HITLManager()

    assert manager.flag_low_confidence_nodes(doc, threshold=0.80) == []
    assert len(manager.flag_desynchronized_nodes(doc)) == 1
