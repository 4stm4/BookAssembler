"""
Artifact bundle packaging for Knowledge Assembly Engine (KAE), RFC 0013.

Provides the content-addressed `.kap` bundle writer/reader used by the build.
"""

from src.artifacts.store import read_kap_bundle, sha256_file, write_kap_bundle

__all__ = [
    "read_kap_bundle",
    "sha256_file",
    "write_kap_bundle",
]
