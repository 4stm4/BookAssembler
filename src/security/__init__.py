"""
Security, Capability Negotiation & Trust Engine for Knowledge Assembly Engine (KAE).

Provides Capability, TrustLevel, CapabilityMismatchError, PluginCapabilities and
SecurityManager according to RFC 0020. The audit trail lives in src.audit.logger.
"""

from src.security.manager import (
    Capability,
    CapabilityMismatchError,
    PluginCapabilities,
    SecurityManager,
    TrustLevel,
    get_security_manager,
    set_security_manager,
)

__all__ = [
    "Capability",
    "CapabilityMismatchError",
    "PluginCapabilities",
    "SecurityManager",
    "TrustLevel",
    "get_security_manager",
    "set_security_manager",
]
