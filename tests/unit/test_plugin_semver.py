"""SemVer gating of plugin loading (RFC 0010 §6.1)."""

import base64

import pytest

from src.plugins.loader import PluginRegistry
from src.plugins.manifest import PluginManifest
from src.plugins.semver import parse_version, satisfies
from src.plugins.signing import generate_keypair, sign_plugin
from src.version import KAE_CORE_VERSION


def test_spec_clauses() -> None:
    assert satisfies("0.1.0", ">=0.1.0") is True
    assert satisfies("0.1.0", ">=0.2.0") is False
    assert satisfies("1.5.0", ">=1.0.0,<2.0.0") is True
    assert satisfies("2.0.0", ">=1.0.0,<2.0.0") is False
    assert satisfies("1.2.3", "==1.2.3") is True
    assert satisfies("1.2.3", "!=1.2.3") is False
    assert satisfies("9.9.9", "*") is True
    assert satisfies("9.9.9", "") is True


def test_short_versions_pad() -> None:
    assert parse_version("1") == (1, 0, 0)
    assert parse_version("1.2") == (1, 2, 0)
    assert satisfies("1.2.0", ">=1.2") is True


def test_malformed_spec_raises() -> None:
    with pytest.raises(ValueError):
        satisfies("1.0.0", ">=not.a.version")


def _signed(tmp_path, kae_core_version: str) -> tuple:
    private_key, public_key = generate_keypair()
    keys_dir = tmp_path / "trusted_keys"
    keys_dir.mkdir()
    (keys_dir / "core.pub").write_bytes(base64.b64encode(public_key))

    payload = b"plugin payload"
    manifest = PluginManifest(
        id="plugin.test",
        version="1.0.0",
        kae_core_version=kae_core_version,
        signature=base64.b64encode(sign_plugin(payload, private_key)).decode(),
        pubkey_id="core",
    )
    return PluginRegistry(tmp_path, keys_dir), manifest, payload


def test_incompatible_plugin_is_rejected_despite_valid_signature(tmp_path) -> None:
    registry, manifest, payload = _signed(tmp_path, ">=99.0.0")

    assert registry.verify_and_register(manifest, payload) is False
    assert registry.registered_plugins == {}


def test_compatible_plugin_registers(tmp_path) -> None:
    registry, manifest, payload = _signed(tmp_path, f">={KAE_CORE_VERSION}")

    assert registry.verify_and_register(manifest, payload) is True
    assert "plugin.test" in registry.registered_plugins
