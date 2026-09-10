"""Tests for Ed25519 plugin signing (RFC 0020 §3)."""
import base64
import tempfile
from pathlib import Path

import pytest

from src.plugins.signing import (
    generate_keypair,
    load_trusted_key,
    sign_plugin,
    verify_plugin_with_trusted_key,
    verify_signature,
)


class TestKeypairGeneration:
    def test_generates_32_byte_keys(self):
        priv, pub = generate_keypair()
        assert len(priv) == 32
        assert len(pub) == 32

    def test_different_each_time(self):
        p1, _ = generate_keypair()
        p2, _ = generate_keypair()
        assert p1 != p2


class TestSignAndVerify:
    def test_valid_signature(self):
        priv, pub = generate_keypair()
        data = b"plugin content here"
        sig = sign_plugin(data, priv)
        assert verify_signature(data, sig, pub)

    def test_invalid_signature(self):
        priv, pub = generate_keypair()
        data = b"plugin content"
        sig = sign_plugin(data, priv)
        assert not verify_signature(b"tampered", sig, pub)

    def test_wrong_key(self):
        priv1, _ = generate_keypair()
        _, pub2 = generate_keypair()
        sig = sign_plugin(b"data", priv1)
        assert not verify_signature(b"data", sig, pub2)


class TestTrustedKeyLoading:
    def test_load_existing_key(self):
        _, pub = generate_keypair()
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test_key.pub"
            p.write_bytes(base64.b64encode(pub))
            loaded = load_trusted_key("test_key", Path(td))
            assert loaded == pub

    def test_missing_key(self):
        with tempfile.TemporaryDirectory() as td:
            assert load_trusted_key("nonexistent", Path(td)) is None


class TestVerifyWithTrustedKey:
    def test_full_flow(self):
        priv, pub = generate_keypair()
        data = b"plugin yaml content"
        sig = sign_plugin(data, priv)
        sig_b64 = base64.b64encode(sig).decode()
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "author1.pub").write_bytes(base64.b64encode(pub))
            assert verify_plugin_with_trusted_key(data, sig_b64, "author1", Path(td))

    def test_unknown_pubkey_id(self):
        priv, pub = generate_keypair()
        sig = sign_plugin(b"data", priv)
        sig_b64 = base64.b64encode(sig).decode()
        with tempfile.TemporaryDirectory() as td:
            assert not verify_plugin_with_trusted_key(b"data", sig_b64, "unknown", Path(td))

    def test_bad_signature_b64(self):
        with tempfile.TemporaryDirectory() as td:
            _, pub = generate_keypair()
            (Path(td) / "k.pub").write_bytes(base64.b64encode(pub))
            assert not verify_plugin_with_trusted_key(b"d", "!!!invalid!!!", "k", Path(td))
