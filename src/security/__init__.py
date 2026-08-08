"""
Security, Capability Negotiation & Audit Log Engine for Knowledge Assembly Engine (KAE).

Provides TrustLevel, CapabilityMismatchError, PluginCapabilities, AuditEntry, AuditLogger,
and SecurityManager according to RFC 0020.
"""

from src.security.manager import (
    AuditEntry,
    AuditLogger,
    CapabilityMismatchError,
    PluginCapabilities,
    SecurityManager,
    TrustLevel,
)

__all__ = [
    "AuditEntry",
    "AuditLogger",
    "CapabilityMismatchError",
    "PluginCapabilities",
    "SecurityManager",
    "TrustLevel",
]
