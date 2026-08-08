"""
Artifact Store & Multi-Level Cache Engine for Knowledge Assembly Engine (KAE).

Implements PackFileBuilder, PackFileReader, ArtifactStore, and MultiLevelCache according to RFC 0013.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, json, hashlib, datetime, time, struct, uuid, zlib)
- Content-addressed storage (immutable, append-only)
- Pack storage (.kap format with index & zlib compression)
- Pinning & Garbage Collection support
- Corruption detection on load
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import struct
import time
from typing import Any, Dict, List, Optional, Set, Union
from uuid import uuid4
import zlib

from src.artifacts.models import (
    ArtifactManifest,
    ArtifactType,
    SnapshotManifest,
)


@dataclass
class ArtifactMeta:
    """
    Legacy metadata for backward compatibility.
    """
    artifact_type: ArtifactType
    sha256_hash: str
    producer_name: str
    artifact_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class PackFileBuilder:
    """
    Builder for binary package storage (.kap) files containing compressed artifacts and a tail index.
    """

    MAGIC = b"KAP1"

    def __init__(self) -> None:
        self._entries: List[tuple[str, bytes]] = []

    def add_entry(self, artifact_id: str, data: bytes) -> None:
        """
        Adds an artifact entry to the pack payload.
        """
        self._entries.append((artifact_id, data))

    def build_pack(self) -> bytes:
        """
        Compresses entries using zlib, builds offset index, and constructs complete .kap binary file.
        """
        out_buf = bytearray()
        out_buf.extend(self.MAGIC)

        index_data: Dict[str, Dict[str, int]] = {}

        for art_id, raw_bytes in self._entries:
            compressed = zlib.compress(raw_bytes)
            offset = len(out_buf)
            comp_len = len(compressed)
            raw_len = len(raw_bytes)

            out_buf.extend(compressed)

            index_data[art_id] = {
                "offset": offset,
                "compressed_len": comp_len,
                "raw_len": raw_len,
            }

        index_bytes = json.dumps(index_data, sort_keys=True).encode("utf-8")
        index_offset = len(out_buf)
        index_len = len(index_bytes)

        out_buf.extend(index_bytes)

        # Footer: 8-byte index_offset (Q), 8-byte index_len (Q), 4-byte MAGIC (4s)
        footer = struct.pack(">QQ4s", index_offset, index_len, self.MAGIC)
        out_buf.extend(footer)

        return bytes(out_buf)


class PackFileReader:
    """
    Reader for binary package storage (.kap) files supporting O(1) random access reads by index.
    """

    MAGIC = b"KAP1"

    def __init__(self, pack_bytes: bytes) -> None:
        if len(pack_bytes) < 20:
            raise ValueError("Invalid .kap file: buffer too short")

        footer = pack_bytes[-20:]
        index_offset, index_len, magic = struct.unpack(">QQ4s", footer)

        if magic != self.MAGIC:
            raise ValueError("Invalid .kap magic bytes in footer")

        index_bytes = pack_bytes[index_offset : index_offset + index_len]
        self._pack_bytes = pack_bytes
        self._index: Dict[str, Dict[str, int]] = json.loads(index_bytes.decode("utf-8"))

    def list_artifacts(self) -> List[str]:
        """
        Returns list of artifact IDs contained within the pack.
        """
        return list(self._index.keys())

    def read_artifact(self, artifact_id: str) -> bytes:
        """
        Reads and decompresses artifact byte payload by artifact_id.
        """
        if artifact_id not in self._index:
            raise KeyError(f"Artifact ID '{artifact_id}' not found in pack index")

        meta = self._index[artifact_id]
        offset = meta["offset"]
        comp_len = meta["compressed_len"]

        compressed_bytes = self._pack_bytes[offset : offset + comp_len]
        decompressed = zlib.decompress(compressed_bytes)

        if len(decompressed) != meta["raw_len"]:
            raise ValueError(
                f"Decompressed length mismatch for '{artifact_id}': "
                f"expected {meta['raw_len']}, got {len(decompressed)}"
            )

        return decompressed


@dataclass
class _CacheEntry:
    value: Any
    expires_at: Optional[float]
    priority_weight: float = 1.0


class ArtifactStore:
    """
    Content-Addressed Storage Engine for Knowledge Assembly Engine (RFC 0013).
    """

    def __init__(self) -> None:
        self._store_bytes: Dict[str, bytes] = {}
        self._manifests: Dict[str, ArtifactManifest] = {}
        self._snapshots: Dict[str, SnapshotManifest] = {}
        self._pinned_ids: Set[str] = set()

    @staticmethod
    def _canonicalize(data: Union[bytes, str, Dict[str, Any]]) -> bytes:
        """
        Converts content data into canonical byte stream.
        """
        if isinstance(data, bytes):
            return data
        elif isinstance(data, str):
            return data.encode("utf-8")
        elif isinstance(data, dict):
            return json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        else:
            raise TypeError(f"Unsupported data type for artifact payload: {type(data)}")

    def put_artifact(
        self,
        content: Union[bytes, str, Dict[str, Any]],
        artifact_type: ArtifactType,
        producer: str,
        producer_version: str,
        inputs: Optional[List[str]] = None,
        provenance_id: str = "",
        schema_version: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactManifest:
        """
        Stores content in append-only content-addressed storage.
        Identifies artifact by artifact_id = sha256(canonical_content).
        """
        raw_bytes = self._canonicalize(content)
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        artifact_id = content_hash

        input_list = inputs if inputs is not None else []
        meta_dict = metadata if metadata is not None else {}

        # Content addressing invariant: if artifact already exists, return existing manifest
        if artifact_id in self._manifests:
            return self._manifests[artifact_id]

        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content_hash=content_hash,
            size_bytes=len(raw_bytes),
            compression_codec="zlib",
            producer=producer,
            producer_version=producer_version,
            schema_version=schema_version,
            inputs=input_list,
            provenance_id=provenance_id,
            metadata=meta_dict,
        )

        self._store_bytes[artifact_id] = raw_bytes
        self._manifests[artifact_id] = manifest

        return manifest

    def get_artifact(self, artifact_id: str) -> bytes:
        """
        Retrieves raw artifact byte content and verifies content hash integrity.
        Raises ValueError (STORAGE_CORRUPTED) if hash mismatch is detected.
        """
        if artifact_id not in self._store_bytes or artifact_id not in self._manifests:
            raise KeyError(f"Artifact with ID '{artifact_id}' not found in store")

        raw_bytes = self._store_bytes[artifact_id]
        manifest = self._manifests[artifact_id]

        computed_hash = hashlib.sha256(raw_bytes).hexdigest()
        if computed_hash != manifest.content_hash:
            raise ValueError(
                f"STORAGE_CORRUPTED: Hash mismatch for artifact '{artifact_id}'. "
                f"Expected {manifest.content_hash}, got {computed_hash}"
            )

        return raw_bytes

    def create_snapshot(
        self, build_id: str, artifact_refs: Dict[str, str]
    ) -> SnapshotManifest:
        """
        Creates a build snapshot mapping keys/roles to artifact IDs.
        """
        # Verify referenced artifacts exist
        for ref_key, art_id in artifact_refs.items():
            if art_id not in self._manifests:
                raise KeyError(
                    f"Artifact ID '{art_id}' referenced by '{ref_key}' does not exist in store"
                )

        snapshot = SnapshotManifest(
            build_id=build_id,
            artifact_refs=dict(artifact_refs),
        )
        self._snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> SnapshotManifest:
        """
        Retrieves SnapshotManifest by snapshot_id.
        """
        if snapshot_id not in self._snapshots:
            raise KeyError(f"Snapshot ID '{snapshot_id}' not found in store")
        return self._snapshots[snapshot_id]

    def pin_artifact(self, artifact_id: str) -> None:
        """
        Pins an artifact to protect it from Garbage Collection.
        """
        if artifact_id not in self._manifests:
            raise KeyError(f"Cannot pin artifact '{artifact_id}': not in store")
        self._pinned_ids.add(artifact_id)

    def unpin_artifact(self, artifact_id: str) -> None:
        """
        Unpins an artifact allowing Garbage Collection if unreferenced.
        """
        self._pinned_ids.discard(artifact_id)

    def run_garbage_collection(self) -> int:
        """
        Deletes unpinned artifacts that are not referenced in any SnapshotManifest.
        Returns the number of collected artifacts.
        """
        referenced_ids: Set[str] = set(self._pinned_ids)

        for snap in self._snapshots.values():
            for art_id in snap.artifact_refs.values():
                referenced_ids.add(art_id)

        all_ids = list(self._manifests.keys())
        collected_count = 0

        for art_id in all_ids:
            if art_id not in referenced_ids:
                del self._manifests[art_id]
                if art_id in self._store_bytes:
                    del self._store_bytes[art_id]
                collected_count += 1

        return collected_count

    # --- Backward compatibility methods ---

    def save_artifact(
        self,
        job_id: str,
        artifact_type: ArtifactType,
        data: Union[bytes, str, Dict[str, Any]],
        producer: str,
    ) -> ArtifactMeta:
        """
        Legacy save_artifact signature for backward compatibility.
        """
        manifest = self.put_artifact(
            content=data,
            artifact_type=artifact_type,
            producer=producer,
            producer_version="1.0.0",
        )

        return ArtifactMeta(
            artifact_id=manifest.artifact_id,
            artifact_type=manifest.artifact_type,
            sha256_hash=manifest.content_hash,
            producer_name=manifest.producer,
        )

    def load_artifact(self, artifact_id: str) -> bytes:
        """
        Alias for get_artifact.
        """
        return self.get_artifact(artifact_id)

    def get_metadata(self, artifact_id: str) -> Optional[ArtifactManifest]:
        """
        Retrieves ArtifactManifest for artifact_id.
        """
        return self._manifests.get(artifact_id)

    def corrupt_artifact_bytes_for_testing(self, artifact_id: str, new_bytes: bytes) -> None:
        """
        Internal test utility to simulate byte corruption in memory.
        """
        if artifact_id in self._store_bytes:
            self._store_bytes[artifact_id] = new_bytes


class MultiLevelCache:
    """
    Multi-Level Cache for caching expensive computation outputs (OCR, LLM, Embeddings).
    """

    def __init__(self) -> None:
        self._store: Dict[str, _CacheEntry] = {}

    @staticmethod
    def compute_cache_key(
        analyzer_name: str,
        version: str,
        input_hashes: List[str],
        config: Dict[str, Any],
    ) -> str:
        """
        Computes deterministic cache key hash for computation inputs.
        """
        raw_key = {
            "analyzer": analyzer_name,
            "version": version,
            "inputs": sorted(input_hashes),
            "config": config,
        }
        encoded = json.dumps(raw_key, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get_cached_computation(self, cache_key: str) -> Optional[Any]:
        """
        Retrieves cached computation value by cache_key.
        """
        entry = self._store.get(cache_key)
        if entry is None:
            return None

        if entry.expires_at is not None and time.time() > entry.expires_at:
            del self._store[cache_key]
            return None

        return entry.value

    def put_cached_computation(
        self, cache_key: str, value: Any, priority_weight: float = 1.0
    ) -> None:
        """
        Stores computation output in cache with priority weight.
        """
        self._store[cache_key] = _CacheEntry(
            value=value,
            expires_at=None,
            priority_weight=priority_weight,
        )

    # --- Backward compatibility methods ---

    def get(self, key_hash: str) -> Optional[Any]:
        """
        Alias for get_cached_computation.
        """
        return self.get_cached_computation(key_hash)

    def set(
        self, key_hash: str, value: Any, ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Alias for put_cached_computation with optional TTL in seconds.
        """
        expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        self._store[key_hash] = _CacheEntry(
            value=value,
            expires_at=expires_at,
            priority_weight=1.0,
        )
