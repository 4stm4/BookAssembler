"""
Provenance & Lineage Layer for Knowledge Assembly Engine (KAE).

Implements SourceLocation, TransformationStep, LineageRecord, and ProvenanceTracker
according to RFC 0011.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, datetime, uuid, hashlib)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Dict, List, Optional, Tuple, Union
from uuid import uuid4


@dataclass
class SourceLocation:
    """
    Exact coordinates and source details for a knowledge element.
    """
    source_uri: str
    source_sha256: str
    page_or_screen_index: int = 0
    bounding_box: Optional[Dict[str, float]] = None
    byte_offset_range: Optional[Tuple[int, int]] = None


@dataclass
class TransformationStep:
    """
    Audit record for a single modification step performed on a knowledge node.
    """
    agent_type: str
    agent_id: str
    agent_version: str
    input_snapshot_hash: str
    output_snapshot_hash: str
    mutation_description: str
    confidence_score: float = 1.0
    step_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class LineageRecord:
    """
    Full provenance and transformation history record for a specific KRM entity.
    """
    entity_id: str
    source_location: SourceLocation
    transformation_history: List[TransformationStep] = field(default_factory=list)


class ProvenanceTracker:
    """
    Tracker for managing entity lineage records and transformation step history.
    """

    def __init__(self) -> None:
        self._records: Dict[str, LineageRecord] = {}

    @staticmethod
    def calculate_content_hash(text_or_data: Union[str, bytes]) -> str:
        """
        Calculates SHA-256 hash for input text or bytes.
        """
        if isinstance(text_or_data, str):
            raw_bytes = text_or_data.encode("utf-8")
        else:
            raw_bytes = text_or_data
        return hashlib.sha256(raw_bytes).hexdigest()

    def register_entity(
        self, entity_id: str, source_location: SourceLocation
    ) -> LineageRecord:
        """
        Registers a new entity with its initial source location coordinates.
        """
        record = LineageRecord(
            entity_id=entity_id,
            source_location=source_location,
            transformation_history=[],
        )
        self._records[entity_id] = record
        return record

    def add_transformation_step(
        self, entity_id: str, step: TransformationStep
    ) -> LineageRecord:
        """
        Appends a transformation step to an existing entity's lineage history.
        """
        record = self.get_lineage(entity_id)
        if record is None:
            raise KeyError(f"Entity '{entity_id}' is not registered in ProvenanceTracker")
        record.transformation_history.append(step)
        return record

    def get_lineage(self, entity_id: str) -> Optional[LineageRecord]:
        """
        Retrieves the lineage record for a given entity_id.
        """
        return self._records.get(entity_id)
