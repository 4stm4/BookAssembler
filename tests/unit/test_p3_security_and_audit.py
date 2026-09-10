"""
Unit tests for P3 Infrastructure Modules (RFC 0020).

Tests:
1. Capability Negotiation & CapabilityMismatchError (RFC 0020 §2.1)
2. Capability enforcement at execution sites (RFC 0020 §2.1)
3. Plugin Signature Verification (RFC 0020 §3)

The immutable audit trail (RFC 0020 §4) is covered against the on-disk chained
logger in tests/unit/test_p0_infrastructure.py — src.audit.logger is the one
wired into the API.
"""

import pytest

from src.security.manager import (
    Capability,
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


def test_plugin_signature_verification(tmp_path) -> None:
    """Ed25519 signature verification against a trusted key (RFC 0020 §3)."""
    import base64

    from src.plugins.signing import generate_keypair, sign_plugin

    sec_mgr = SecurityManager(trust_level=TrustLevel.VERIFIED_ONLY)

    priv, pub = generate_keypair()
    (tmp_path / "core.pub").write_bytes(base64.b64encode(pub))
    plugin_bytes = b"fake plugin payload"
    sig_b64 = base64.b64encode(sign_plugin(plugin_bytes, priv)).decode()

    # Valid signature
    assert sec_mgr.verify_plugin_signature(
        plugin_bytes, sig_b64, "core", keys_dir=tmp_path
    ) is True

    # Tampered payload
    assert sec_mgr.verify_plugin_signature(
        b"tampered", sig_b64, "core", keys_dir=tmp_path
    ) is False

    # Unknown key id
    assert sec_mgr.verify_plugin_signature(
        plugin_bytes, sig_b64, "nope", keys_dir=tmp_path
    ) is False


def test_enforce_blocks_ungranted_capability() -> None:
    """A capability absent from the grant list is refused (RFC 0020 §2.1)."""
    sec_mgr = SecurityManager(granted_capabilities=[Capability.READ_SEP_STORAGE])

    sec_mgr.enforce(Capability.READ_SEP_STORAGE)

    with pytest.raises(PermissionError, match="EXECUTE_LATEX_SANDBOX"):
        sec_mgr.enforce(Capability.EXECUTE_LATEX_SANDBOX)


def test_capabilities_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("KAE_CAPABILITIES", "ACCESS_NETWORK_LLM, bogus_capability")
    sec_mgr = SecurityManager.from_env()

    assert sec_mgr.granted == {Capability.ACCESS_NETWORK_LLM}

    monkeypatch.delenv("KAE_CAPABILITIES")
    assert SecurityManager.from_env().granted == set(Capability)


def test_latex_compilation_requires_capability(tmp_path, monkeypatch) -> None:
    """The xelatex execution site actually asks before running (RFC 0020 §1)."""
    from src.assembler import latex_builder
    from src.security.manager import set_security_manager

    set_security_manager(SecurityManager(granted_capabilities=[]))
    try:
        with pytest.raises(PermissionError, match="EXECUTE_LATEX_SANDBOX"):
            latex_builder.compile_xelatex(str(tmp_path / "book.tex"), str(tmp_path))
    finally:
        set_security_manager(None)
