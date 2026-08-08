"""
Artifact & Storage Models according to RFC 0013.

Implements ArtifactType, StorageTier, ArtifactManifest, and SnapshotManifest.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, enum, typing, datetime, uuid)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List
from uuid import uuid4


class ArtifactType(Enum):
    """
    Classifications of artifacts managed by Knowledge Assembly Engine Storage Engine.
    """
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"
    RAW_KRM = "RAW_KRM"
    NORMALIZED_KRM = "NORMALIZED_KRM"
    LAYOUT_KRM = "LAYOUT_KRM"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    READING_GRAPH = "READING_GRAPH"
    OCR_RESULT = "OCR_RESULT"
    TABLE_BLOCK = "TABLE_BLOCK"
    FIGURE_BLOCK = "FIGURE_BLOCK"
    CHUNKS_MANIFEST = "CHUNKS_MANIFEST"
    RAG_GRAPH = "RAG_GRAPH"
    EMBEDDINGS = "EMBEDDINGS"
    DATASET = "DATASET"


class StorageTier(Enum):
    """
    Multi-tier storage engine tiers.
    """
    L0_RAM = "L0_RAM"
    L1_NVME_CACHE = "L1_NVME_CACHE"
    L2_ACTIVE_STORE = "L2_ACTIVE_STORE"
    L3_ARCHIVE_STORE = "L3_ARCHIVE_STORE"


@dataclass
class ArtifactManifest:
    """
    Metadata manifest describing an immutable content-addressed artifact in ArtifactStore.
    """
    artifact_id: str
    artifact_type: ArtifactType
    content_hash: str
    size_bytes: int
    compression_codec: str
    producer: str
    producer_version: str
    schema_version: int = 1
    inputs: List[str] = field(default_factory=list)
    provenance_id: str = ""
    creation_time_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SnapshotManifest:
    """
    Reproducible build snapshot referencing exact immutable artifact IDs.
    """
    build_id: str
    artifact_refs: Dict[str, str]
    snapshot_id: str = field(default_factory=lambda: str(uuid4()))
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
