"""
Unit tests for P3 Infrastructure Modules (RFC 0020).

Tests:
1. Capability Negotiation & CapabilityMismatchError (RFC 0020)
2. Plugin Signature Verification (RFC 0020)
3. Audit Log Engine & Immutable Event History (RFC 0020)
"""

import hashlib
from src.security.manager import (
    AuditEntry,
    AuditLogger,
    CapabilityMismatchError,
    PluginCapabilities,
    SecurityManager,
    TrustLevel,
)


def test_capability_negotiation_pass_and_fail() -> None:
    """
    Test capability negotiation: passes when requested features are within policy,
    raises CapabilityMismatchError when plugin requests forbidden network or filesystem access.
    """
    sec_mgr = SecurityManager(trust_level=TrustLevel.VERIFIED_ONLY)

    system_policy = PluginCapabilities(
        requires_krm_version="1.0.0",
        requires_graph_api=True,
        allow_network=False,
        allow_filesystem=False,
    )

    # Valid request matching system policy
    valid_req = PluginCapabilities(
        requires_krm_version="1.0.0",
        requires_graph_api=True,
        allow_network=False,
        allow_filesystem=False,
    )
    assert sec_mgr.negotiate_capabilities(valid_req, system_policy) is True

    # Invalid request: asking for network access
    network_req = PluginCapabilities(
        requires_krm_version="1.0.0",
        requires_graph_api=False,
        allow_network=True,
        allow_filesystem=False,
    )

    try:
        sec_mgr.negotiate_capabilities(network_req, system_policy)
        assert False, "Should have raised CapabilityMismatchError for network request"
    except CapabilityMismatchError as exc:
        assert "allow_network=True" in str(exc)

    # Invalid request: asking for filesystem access
    fs_req = PluginCapabilities(
        requires_krm_version="1.0.0",
        requires_graph_api=False,
        allow_network=False,
        allow_filesystem=True,
    )

    try:
        sec_mgr.negotiate_capabilities(fs_req, system_policy)
        assert False, "Should have raised CapabilityMismatchError for filesystem request"
    except CapabilityMismatchError as exc:
        assert "allow_filesystem=True" in str(exc)


def test_plugin_signature_verification() -> None:
    """
    Test plugin digital signature verification using public_key digest matching.
    """
    sec_mgr = SecurityManager(trust_level=TrustLevel.VERIFIED_ONLY)

    plugin_id = "plugin_layout_analyzer"
    public_key = "pubkey_kae_core_2026_x86"
    valid_signature = hashlib.sha256(f"{plugin_id}:{public_key}".encode("utf-8")).hexdigest()

    # Valid signature check
    assert sec_mgr.verify_plugin_signature(plugin_id, valid_signature, public_key) is True

    # Invalid signature check
    assert sec_mgr.verify_plugin_signature(plugin_id, "invalid_signature_hex", public_key) is False


def test_audit_logger_event_recording_and_target_filtering() -> None:
    """
    Test recording audit events, payload SHA-256 hashing, and retrieving history by target_id.
    """
    logger = AuditLogger()

    actor_id = "human_reviewer_01"
    target_node = "krm_node_paragraph_404"
    payload = {"edited_text": "Corrected text content", "approved": True}

    entry1 = logger.log_event(
        actor_id=actor_id,
        action_type="HUMAN_CORRECTION",
        target_id=target_node,
        payload=payload,
    )

    assert entry1.actor_id == actor_id
    assert entry1.action_type == "HUMAN_CORRECTION"
    assert entry1.target_id == target_node
    assert len(entry1.payload_hash) == 64

    # Log second event for same target
    entry2 = logger.log_event(
        actor_id="system_agent_v2",
        action_type="KG_EDGE_ADDED",
        target_id=target_node,
        payload="Linked to section 2.1",
    )

    # Log event for another target
    logger.log_event(
        actor_id="system_agent_v2",
        action_type="TOMBSTONE_NODE",
        target_id="krm_node_paragraph_500",
        payload="Redundant node removed",
    )

    target_history = logger.get_history_for_target(target_node)
    assert len(target_history) == 2
    assert target_history[0].entry_id == entry1.entry_id
    assert target_history[1].entry_id == entry2.entry_id


if __name__ == "__main__":
    test_capability_negotiation_pass_and_fail()
    test_plugin_signature_verification()
    test_audit_logger_event_recording_and_target_filtering()
    print("ALL P3 SECURITY & AUDIT TESTS PASSED!")
