"""
Security, Capability Negotiation & Trust Engine for Knowledge Assembly Engine (KAE).

Implements Capability, TrustLevel, CapabilityMismatchError, PluginCapabilities and
SecurityManager according to RFC 0020. The immutable audit trail (RFC 0020 §4) lives
in src.audit.logger — that is the chained, on-disk logger wired into the API.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, enum, typing, os, pathlib)
"""

from dataclasses import dataclass
from enum import Enum
import logging
import os
from pathlib import Path
from typing import Iterable, Optional, Set

log = logging.getLogger(__name__)


class Capability(str, Enum):
    """
    Capabilities a plugin or worker node must be granted before acting (RFC 0020 §2.1).
    """
    READ_SEP_STORAGE = "READ_SEP_STORAGE"
    WRITE_SEP_STORAGE = "WRITE_SEP_STORAGE"
    EXECUTE_LATEX_SANDBOX = "EXECUTE_LATEX_SANDBOX"
    ACCESS_NETWORK_LLM = "ACCESS_NETWORK_LLM"


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


class SecurityManager:
    """
    Security manager for capability enforcement, plugin capability negotiation,
    and signature verification.
    """

    def __init__(
        self,
        trust_level: TrustLevel = TrustLevel.VERIFIED_ONLY,
        granted_capabilities: Optional[Iterable[Capability]] = None,
    ) -> None:
        self.trust_level = trust_level
        self.granted: Set[Capability] = (
            set(Capability)
            if granted_capabilities is None
            else set(granted_capabilities)
        )

    def enforce(self, capability: Capability) -> None:
        """
        Raises PermissionError unless the capability was granted (RFC 0020 §2.1).
        """
        if capability not in self.granted:
            raise PermissionError(f"Access denied for capability: {capability.value}")

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

    @classmethod
    def from_env(cls) -> "SecurityManager":
        """
        Builds a manager from KAE_CAPABILITIES (comma-separated). Unset grants
        everything, so an operator opts into restriction rather than out of it.
        """
        raw = os.environ.get("KAE_CAPABILITIES", "").strip()
        if not raw:
            return cls()

        granted: Set[Capability] = set()
        for name in raw.split(","):
            name = name.strip().upper()
            if not name:
                continue
            try:
                granted.add(Capability(name))
            except ValueError:
                log.warning("Unknown capability in KAE_CAPABILITIES: %s", name)
        return cls(granted_capabilities=granted)

    def verify_plugin_signature(
        self, plugin_bytes: bytes, signature_b64: str, pubkey_id: str,
        keys_dir: Optional[Path] = None,
    ) -> bool:
        """Verify a plugin's Ed25519 signature against a trusted key (RFC 0020 §3).

        Delegates to src.plugins.signing — the previous implementation compared
        sha256("{plugin_id}:{public_key}"), which anyone knowing the (public)
        id and key could forge.
        """
        from src.plugins.signing import verify_plugin_with_trusted_key

        if not plugin_bytes or not signature_b64 or not pubkey_id:
            return False
        return verify_plugin_with_trusted_key(
            plugin_bytes, signature_b64, pubkey_id, keys_dir
        )


_manager: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    """Process-wide manager used by the capability checks at execution sites."""
    global _manager
    if _manager is None:
        _manager = SecurityManager.from_env()
    return _manager


def set_security_manager(manager: Optional[SecurityManager]) -> None:
    """Override the process-wide manager (None resets it to the environment default)."""
    global _manager
    _manager = manager
