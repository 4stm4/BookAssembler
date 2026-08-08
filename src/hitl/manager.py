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

from src.krm.models import BaseKRMNode, ContainerUnit, KnowledgeDocument
from src.provenance.models import ProvenanceTracker, SourceLocation, TransformationStep


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


class HITLManager:
    """
    Manager for interactive Ground Truth queue, low-confidence node flagging, and human edits.
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, HITLTaskItem] = {}

    def flag_low_confidence_nodes(
        self, doc: KnowledgeDocument, threshold: float = 0.7
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

        # Apply payload attributes to node
        for key, value in correction_payload.items():
            if key == "rejected":
                continue
            if hasattr(node, key):
                setattr(node, key, value)
            else:
                node.metadata[key] = value

        # Human correction boosts confidence to 1.0
        node.confidence_score = 1.0

        # Update task status
        is_rejected = correction_payload.get("rejected", False)
        if is_rejected:
            task.status = CorrectionStatus.REJECTED_BY_HUMAN
        else:
            task.status = CorrectionStatus.APPROVED_BY_HUMAN
        task.reviewer_id = reviewer_id

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
        """
        Recursively collects all KRM nodes from document root containers.
        """
        nodes: List[BaseKRMNode] = []

        def _traverse(n: BaseKRMNode) -> None:
            nodes.append(n)
            if isinstance(n, ContainerUnit):
                for child in n.children:
                    _traverse(child)

        for root in doc.root_containers:
            _traverse(root)

        return nodes

    def _find_node_by_id(
        self, doc: KnowledgeDocument, target_id: str
    ) -> Optional[BaseKRMNode]:
        """
        Finds a node by ID in document.
        """
        all_nodes = self._get_all_nodes(doc)
        for n in all_nodes:
            if n.id == target_id:
                return n
        return None
