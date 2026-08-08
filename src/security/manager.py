"""
Security, Capability Negotiation & Audit Log Engine for Knowledge Assembly Engine (KAE).

Implements TrustLevel, CapabilityMismatchError, PluginCapabilities, AuditEntry, AuditLogger,
and SecurityManager according to RFC 0020.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, enum, typing, json, hashlib, datetime, uuid)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional
from uuid import uuid4


class TrustLevel(Enum):
    """
    Plugin trust level classifications.
    """
    UNTRUSTED = "UNTRUSTED"
    COMMUNITY_SIGNED = "COMMUNITY_SIGNED"
    VERIFIED_ONLY = "VERIFIED_ONLY"
    CORE_TRUSTED = "CORE_TRUSTED"


class CapabilityMismatchError(Exception):
    """
    Raised when requested plugin capabilities exceed system safety policy constraints.
    """
    pass


@dataclass
class PluginCapabilities:
    """
    Capability requirements requested by a plugin or enforced by system security policy.
    """
    requires_krm_version: str = "1.0.0"
    requires_graph_api: bool = False
    allow_network: bool = False
    allow_filesystem: bool = False


@dataclass
class AuditEntry:
    """
    Immutable audit log record for security, transformation, and mutation operations.
    """
    actor_id: str
    action_type: str
    target_id: str
    payload_hash: str
    entry_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AuditLogger:
    """
    Immutable audit trail recorder for operations across the Knowledge Assembly Engine.
    """

    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    def log_event(
        self, actor_id: str, action_type: str, target_id: str, payload: Any
    ) -> AuditEntry:
        """
        Hashes event payload and records an immutable AuditEntry.
        """
        if isinstance(payload, bytes):
            raw_bytes = payload
        elif isinstance(payload, str):
            raw_bytes = payload.encode("utf-8")
        elif isinstance(payload, (dict, list)):
            raw_bytes = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        else:
            raw_bytes = str(payload).encode("utf-8")

        payload_hash = hashlib.sha256(raw_bytes).hexdigest()

        entry = AuditEntry(
            actor_id=actor_id,
            action_type=action_type,
            target_id=target_id,
            payload_hash=payload_hash,
        )

        self._entries.append(entry)
        return entry

    def get_history_for_target(self, target_id: str) -> List[AuditEntry]:
        """
        Retrieves all audit entries for a specific target_id.
        """
        return [entry for entry in self._entries if entry.target_id == target_id]


class SecurityManager:
    """
    Security manager for plugin capability negotiation and signature verification.
    """

    def __init__(self, trust_level: TrustLevel = TrustLevel.VERIFIED_ONLY) -> None:
        self.trust_level = trust_level

    def negotiate_capabilities(
        self, requested: PluginCapabilities, system_policy: PluginCapabilities
    ) -> bool:
        """
        Validates requested plugin capabilities against system policy.
        Raises CapabilityMismatchError if constraints are violated.
        """
        if requested.allow_network and not system_policy.allow_network:
            raise CapabilityMismatchError(
                "Plugin requested network access ('allow_network=True'), but system policy denies network access."
            )

        if requested.allow_filesystem and not system_policy.allow_filesystem:
            raise CapabilityMismatchError(
                "Plugin requested filesystem access ('allow_filesystem=True'), but system policy denies filesystem access."
            )

        if requested.requires_graph_api and not system_policy.requires_graph_api:
            raise CapabilityMismatchError(
                "Plugin requires Graph API access, but system policy disables Graph API access."
            )

        return True

    def verify_plugin_signature(
        self, plugin_id: str, signature: str, public_key: str
    ) -> bool:
        """
        Verifies plugin signature using public_key digest matching.
        """
        if not plugin_id or not signature or not public_key:
            return False

        expected_sig = hashlib.sha256(f"{plugin_id}:{public_key}".encode("utf-8")).hexdigest()
        return signature == expected_sig
