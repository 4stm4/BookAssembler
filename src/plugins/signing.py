"""Ed25519 plugin signing and verification (RFC 0020 §3)."""

import base64
import hashlib
import os
import re
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

_TRUSTED_KEYS_DIR = Path("plugins/trusted_keys")


def generate_keypair() -> Tuple[bytes, bytes]:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    public_bytes = private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    return private_bytes, public_bytes


def sign_plugin(plugin_bytes: bytes, private_key_bytes: bytes) -> bytes:
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    return private_key.sign(plugin_bytes)


def verify_signature(
    plugin_bytes: bytes, signature: bytes, public_key_bytes: bytes
) -> bool:
    public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        public_key.verify(signature, plugin_bytes)
        return True
    except Exception:
        return False


def load_trusted_key(pubkey_id: str, keys_dir: Optional[Path] = None) -> Optional[bytes]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", pubkey_id):
        return None
    d = keys_dir or _TRUSTED_KEYS_DIR
    key_path = d / f"{pubkey_id}.pub"
    if not key_path.exists():
        return None
    raw = key_path.read_bytes().strip()
    try:
        return base64.b64decode(raw)
    except Exception:
        return raw


def verify_plugin_with_trusted_key(
    plugin_bytes: bytes,
    signature_b64: str,
    pubkey_id: str,
    keys_dir: Optional[Path] = None,
) -> bool:
    pub_bytes = load_trusted_key(pubkey_id, keys_dir)
    if pub_bytes is None:
        return False
    try:
        sig_bytes = base64.b64decode(signature_b64)
    except Exception:
        return False
    return verify_signature(plugin_bytes, sig_bytes, pub_bytes)
