"""Source digest in lineage records and prompt hashing (RFC 0011 §3.1, RFC 0012 §4)."""

import hashlib
import io

from src.adapters.text_markdown import MarkdownSourceAdapter
from src.assembler.translator import _build_translate_prompt, _record_translation
from src.hitl.manager import HITLManager
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock, ProvenanceInfo
from src.provenance.models import ProvenanceTracker


def test_adapter_records_the_source_digest() -> None:
    payload = b"# Title\n\nSome text.\n"

    doc = MarkdownSourceAdapter().parse(io.BytesIO(payload), "file://doc.md")

    assert doc.provenance_info.source_sha256 == hashlib.sha256(payload).hexdigest()


def test_human_correction_lineage_carries_the_source_digest() -> None:
    paragraph = ParagraphBlock(confidence_score=0.5)
    doc = KnowledgeDocument(
        source_uri="file://doc.md",
        root_containers=[ContainerUnit(children=[paragraph])],
        provenance_info=ProvenanceInfo(
            adapter_name="MarkdownSourceAdapter",
            extraction_timestamp_utc="2026-01-01T00:00:00+00:00",
            source_sha256="a" * 64,
        ),
    )
    manager = HITLManager()
    task = manager.flag_low_confidence_nodes(doc)[0]
    tracker = ProvenanceTracker()

    manager.apply_human_correction(
        doc, task.task_id, {"text": "fixed"}, "reviewer-1", tracker
    )

    lineage = tracker.get_lineage(paragraph.id)
    assert lineage.source_location.source_sha256 == "a" * 64


def test_translation_records_the_prompt_hash() -> None:
    block = ParagraphBlock()

    _record_translation(block, "MOV R0, R1", "MOV R0, R1", "RU")

    expected = hashlib.sha256(
        _build_translate_prompt("MOV R0, R1", "RU").encode()
    ).hexdigest()
    transformation = block.metadata["translations"]["RU"]["transformation"]
    assert transformation["prompt_hash"] == f"sha256:{expected}"
