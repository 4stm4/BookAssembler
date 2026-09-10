"""
Human-in-the-Loop & Interactive Ground Truth Engine for Knowledge Assembly Engine (KAE).

Implements CorrectionStatus, HITLTaskItem, and HITLManager according to RFC 0016.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, enum, typing, uuid)
- Preserves full audit lineage via ProvenanceTracker without overwriting history
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.krm.models import BaseKRMNode, KnowledgeDocument
from src.krm.traversal import walk
from src.provenance.models import ProvenanceTracker, SourceLocation, TransformationStep


# Attributes a human reviewer may set directly on a KRM node. Anything else in
# a correction payload is stored under node.metadata instead of being written
# through setattr — the endpoint takes the payload straight from the request
# body, and an unfiltered setattr let a client rewrite `id`, flip
# `is_tombstoned`, or replace `children`/`inlines` with arbitrary values,
# breaking node identity and KRM invariants (RFC 0002 §inv3/§inv4).
_CORRECTABLE_FIELDS = frozenset({
    "text", "title", "caption_text", "entry_text", "raw_text", "code_text",
    "pseudocode", "latex_expression", "definition_text", "message_text",
    "term", "marker", "label",
    "programming_language", "list_style", "kind", "severity", "ephemera_type",
    "sidebar_type", "statement_type", "page_role", "target_type",
    "algorithm_name", "algorithm_number", "formula_number", "chapter_number",
    "is_bold", "is_italic",
    "confidence_score", "extraction_confidence", "classification_confidence",
})


class CorrectionStatus(Enum):
    """
    Status lifecycle for Human-in-the-Loop correction task items.
    """
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    APPROVED_BY_HUMAN = "APPROVED_BY_HUMAN"
    REJECTED_BY_HUMAN = "REJECTED_BY_HUMAN"
    AUTO_ACCEPTED = "AUTO_ACCEPTED"


@dataclass
class HITLTaskItem:
    """
    Interactive task item representing a KRM node flagged for human review or correction.
    """
    target_krm_id: str
    current_confidence: float
    suggested_fix: Dict[str, Any] = field(default_factory=dict)
    status: CorrectionStatus = CorrectionStatus.PENDING_HUMAN_REVIEW
    reviewer_id: Optional[str] = None
    task_id: str = field(default_factory=lambda: str(uuid4()))
    correction_history: List[Dict[str, Any]] = field(default_factory=list)


class HITLManager:
    """
    Manager for interactive Ground Truth queue, low-confidence node flagging, and human edits.
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, HITLTaskItem] = {}

    def flag_low_confidence_nodes(
        self, doc: KnowledgeDocument, threshold: float = 0.80
    ) -> List[HITLTaskItem]:
        """
        Scans all nodes in a KnowledgeDocument and flags nodes with confidence < threshold.
        """
        flagged_items: List[HITLTaskItem] = []
        nodes = self._get_all_nodes(doc)

        for node in nodes:
            if not node.is_tombstoned and node.confidence_score < threshold:
                task = HITLTaskItem(
                    target_krm_id=node.id,
                    current_confidence=node.confidence_score,
                    suggested_fix={},
                    status=CorrectionStatus.PENDING_HUMAN_REVIEW,
                )
                self._tasks[task.task_id] = task
                flagged_items.append(task)

        return flagged_items

    def flag_desynchronized_nodes(
        self, doc: KnowledgeDocument, wer_threshold: float = 0.15
    ) -> List[HITLTaskItem]:
        """
        Queues translated segments whose technical drift exceeds the threshold
        (RFC 0015 §4). Drift is recorded per segment by the translator; a segment
        that lost mnemonics, register names or formulas needs a human even when
        the node's own confidence is high.
        """
        flagged_items: List[HITLTaskItem] = []

        for node in self._get_all_nodes(doc):
            if node.is_tombstoned:
                continue
            translations = (node.metadata or {}).get("translations") or {}
            for target_lang, segment in translations.items():
                drift = (segment or {}).get("drift") or {}
                wer = float(drift.get("protected_token_wer", 0.0))
                if wer <= wer_threshold:
                    continue
                task = HITLTaskItem(
                    target_krm_id=node.id,
                    current_confidence=node.confidence_score,
                    suggested_fix={
                        "reason": "DESYNC_TEXT_DRIFT",
                        "target_lang": target_lang,
                        "protected_token_wer": wer,
                    },
                    status=CorrectionStatus.PENDING_HUMAN_REVIEW,
                )
                self._tasks[task.task_id] = task
                flagged_items.append(task)

        return flagged_items

    def apply_human_correction(
        self,
        doc: KnowledgeDocument,
        task_id: str,
        correction_payload: Dict[str, Any],
        reviewer_id: str,
        tracker: Optional[ProvenanceTracker] = None,
    ) -> None:
        """
        Applies human correction payload to the target node, updates status, and records provenance step.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"HITL task with ID '{task_id}' not found")

        node = self._find_node_by_id(doc, task.target_krm_id)
        if node is None:
            raise KeyError(f"Target KRM node '{task.target_krm_id}' not found in document")

        input_snapshot = f"Node(id={node.id}, confidence={node.confidence_score}, metadata={node.metadata})"

        before_state = {
            "confidence_score": node.confidence_score,
            "metadata": dict(node.metadata) if node.metadata else {},
        }
        for key in correction_payload:
            if key != "rejected" and hasattr(node, key):
                before_state[key] = getattr(node, key)

        # Apply payload attributes to node. Only whitelisted scalar fields go
        # through setattr; `metadata` merges; everything else is recorded under
        # metadata rather than written blindly onto the node.
        for key, value in correction_payload.items():
            if key == "rejected":
                continue
            if key == "metadata" and isinstance(value, dict):
                node.metadata.update(value)
                continue
            if key in _CORRECTABLE_FIELDS and hasattr(node, key):
                current = getattr(node, key)
                if isinstance(current, bool):
                    value = bool(value)
                elif isinstance(current, (int, float)) and isinstance(value, (int, float)):
                    value = type(current)(value)
                elif current is not None and not isinstance(value, type(current)):
                    raise ValueError(
                        f"HITL correction for '{key}' expects "
                        f"{type(current).__name__}, got {type(value).__name__}"
                    )
                setattr(node, key, value)
            else:
                node.metadata[str(key)] = value

        # Human correction boosts confidence to 1.0
        node.confidence_score = 1.0

        # Update task status
        is_rejected = correction_payload.get("rejected", False)
        if is_rejected:
            task.status = CorrectionStatus.REJECTED_BY_HUMAN
        else:
            task.status = CorrectionStatus.APPROVED_BY_HUMAN
        task.reviewer_id = reviewer_id

        after_state = {
            "confidence_score": node.confidence_score,
            "metadata": dict(node.metadata) if node.metadata else {},
        }
        for key in correction_payload:
            if key != "rejected" and hasattr(node, key):
                after_state[key] = getattr(node, key)

        from datetime import datetime, timezone
        task.correction_history.append({
            "before": before_state,
            "after": after_state,
            "reviewer_id": reviewer_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        output_snapshot = f"Node(id={node.id}, confidence={node.confidence_score}, metadata={node.metadata})"

        # Record provenance step if tracker is provided
        if tracker is not None:
            input_hash = tracker.calculate_content_hash(input_snapshot)
            output_hash = tracker.calculate_content_hash(output_snapshot)

            if tracker.get_lineage(node.id) is None:
                source_loc = SourceLocation(
                    source_uri=doc.source_uri or "unknown_doc",
                    source_sha256="",
                )
                tracker.register_entity(node.id, source_loc)

            step = TransformationStep(
                agent_type="human",
                agent_id=reviewer_id,
                agent_version="1.0.0",
                input_snapshot_hash=input_hash,
                output_snapshot_hash=output_hash,
                mutation_description=f"Human correction applied by {reviewer_id}",
                confidence_score=1.0,
            )
            tracker.add_transformation_step(node.id, step)

    def get_task(self, task_id: str) -> Optional[HITLTaskItem]:
        """
        Retrieves a task item by ID.
        """
        return self._tasks.get(task_id)

    @staticmethod
    def _get_all_nodes(doc: KnowledgeDocument) -> List[BaseKRMNode]:
        """Every KRM node in the document (RFC 0002 §3), lists/callouts/sidebars
        included — the hand-rolled walk here skipped those, so a low-confidence
        block inside a list was never flagged for review."""
        return [n for n in walk(doc) if isinstance(n, BaseKRMNode)]

    def _find_node_by_id(
        self, doc: KnowledgeDocument, target_id: str
    ) -> Optional[BaseKRMNode]:
        """Finds a node by ID anywhere in the document tree."""
        for n in walk(doc):
            if isinstance(n, BaseKRMNode) and n.id == target_id:
                return n
        return None
