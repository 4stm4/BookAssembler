# RFC 0020: Security and Trust Architecture

| Status | Version | Date | Author |
| :--- | :--- | :--- | :--- |
| **Accepted** | 1.0.0 | 2026-08-08 | Core Architecture Team |

---

## 1. Executive Summary

RFC 0020 establishes the security model, capability negotiation, plugin signature verification, and immutable audit logging for KAE. The security framework ensures that untrusted third-party plugins or LaTeX macro executions run inside restricted sandboxes without risking access to secret environment variables or host filesystems.

---

## 2. Core Security Components

### 2.1 Security Manager & Capability Negotiation
Plugins and external worker nodes declare required capabilities (e.g., `READ_SEP_STORAGE`, `EXECUTE_DOCKER`, `CALL_LLM_API`). Permissions not explicitly granted in project configuration are blocked:

```python
class Capability(str, Enum):
    READ_SEP_STORAGE = "READ_SEP_STORAGE"
    WRITE_SEP_STORAGE = "WRITE_SEP_STORAGE"
    EXECUTE_LATEX_SANDBOX = "EXECUTE_LATEX_SANDBOX"
    ACCESS_NETWORK_LLM = "ACCESS_NETWORK_LLM"

class SecurityManager:
    def __init__(self, granted_capabilities: list[Capability]):
        self.granted = set(granted_capabilities)

    def enforce(self, capability: Capability):
        if capability not in self.granted:
            raise PermissionError(f"Access denied for capability: {capability}")
```

---

## 3. Plugin Digital Signature Verification

All analyzer plugins loaded dynamically must present an Ed25519 cryptographic signature verified against trusted public keys in `.kae/trusted_keys`:

```python
from cryptography.hazmat.primitives.asymmetric import ed25519

def verify_plugin_signature(plugin_bytes: bytes, signature: bytes, public_key_bytes: bytes) -> bool:
    public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        public_key.verify(signature, plugin_bytes)
        return True
    except Exception:
        return False
```

---

## 4. Immutable Audit Trail (`AuditLogger`)

All security events, human HITL approvals, LLM prompt dispatches, and storage writes are written to an append-only, SHA-256 chained audit log (`.kae/audit.log`):

```json
{
  "sequence": 1042,
  "prev_hash": "a1b2c3d4e5f6...",
  "timestamp": "2026-08-08T12:50:00Z",
  "actor": "operator-lead",
  "event_type": "HITL_NODE_CORRECTION",
  "target_krm_id": "krm-node-fig-4.1",
  "entry_hash": "c7d8e9f0a1b2..."
}
```
