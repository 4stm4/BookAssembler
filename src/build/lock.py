"""
Reproducible Builds & Lock Engine for Knowledge Assembly Engine (KAE).

Implements BuildLockManifest and BuildLockManager according to RFC 0012.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, json, hashlib, datetime, uuid, pathlib)
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import BinaryIO, Dict, Union
from uuid import uuid4


@dataclass
class BuildLockManifest:
    """
    Lockfile manifest (kae.lock) storing deterministic build component and artifact hashes.
    """
    source_uri: str
    source_sha256: str
    kae_core_version: str
    recipe_id: str
    recipe_version: str
    components_hashes: Dict[str, str]
    artifacts_hashes: Dict[str, str]
    schema_version: str = "1.0"
    build_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_json(self) -> str:
        """
        Serializes BuildLockManifest to a formatted JSON string.
        """
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> "BuildLockManifest":
        """
        Deserializes BuildLockManifest from a JSON string.
        """
        data = json.loads(json_str)
        return cls(
            schema_version=data.get("schema_version", "1.0"),
            build_id=data["build_id"],
            timestamp_utc=data["timestamp_utc"],
            source_uri=data["source_uri"],
            source_sha256=data["source_sha256"],
            kae_core_version=data["kae_core_version"],
            recipe_id=data["recipe_id"],
            recipe_version=data["recipe_version"],
            components_hashes=dict(data.get("components_hashes", {})),
            artifacts_hashes=dict(data.get("artifacts_hashes", {})),
        )


class BuildLockManager:
    """
    Manager for generating and verifying reproducible build lock manifests (kae.lock).
    """

    @staticmethod
    def calculate_sha256(stream_or_bytes: Union[BinaryIO, bytes]) -> str:
        """
        Computes SHA-256 hex digest for a binary stream or byte array.
        """
        hasher = hashlib.sha256()
        if isinstance(stream_or_bytes, bytes):
            hasher.update(stream_or_bytes)
        else:
            chunk = stream_or_bytes.read(65536)
            while chunk:
                hasher.update(chunk)
                chunk = stream_or_bytes.read(65536)
        return hasher.hexdigest()

    @classmethod
    def create_lock(
        cls,
        source_uri: str,
        source_bytes: bytes,
        recipe_id: str,
        recipe_version: str,
        components: Dict[str, str],
        artifacts: Dict[str, bytes],
        kae_core_version: str = "0.1.0",
    ) -> BuildLockManifest:
        """
        Generates a BuildLockManifest given source content, recipe info, component hashes, and artifacts.
        """
        source_sha256 = cls.calculate_sha256(source_bytes)

        artifact_hashes: Dict[str, str] = {}
        for name, art_bytes in sorted(artifacts.items()):
            artifact_hashes[name] = cls.calculate_sha256(art_bytes)

        comp_hashes = {k: v for k, v in sorted(components.items())}

        return BuildLockManifest(
            source_uri=source_uri,
            source_sha256=source_sha256,
            kae_core_version=kae_core_version,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            components_hashes=comp_hashes,
            artifacts_hashes=artifact_hashes,
        )

    @staticmethod
    def verify_reproducibility(
        current_manifest: BuildLockManifest,
        reference_manifest: BuildLockManifest,
    ) -> bool:
        """
        Verifies whether current build manifest matches reference manifest across all hashes and versions.
        """
        if current_manifest.source_sha256 != reference_manifest.source_sha256:
            return False
        if current_manifest.recipe_id != reference_manifest.recipe_id:
            return False
        if current_manifest.recipe_version != reference_manifest.recipe_version:
            return False
        if current_manifest.kae_core_version != reference_manifest.kae_core_version:
            return False
        if current_manifest.components_hashes != reference_manifest.components_hashes:
            return False
        if current_manifest.artifacts_hashes != reference_manifest.artifacts_hashes:
            return False

        return True
