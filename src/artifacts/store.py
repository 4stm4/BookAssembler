"""
Artifact bundle writer/reader for Knowledge Assembly Engine (KAE), RFC 0013.

A build's deliverables are packed into a content-addressed `.kap` bundle: a
gzip tar whose manifest carries the SHA-256 of every artifact, with archive
timestamps and ownership pinned so identical inputs produce identical bundles.

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (typing, json, hashlib, os, tarfile)
"""

import hashlib
import io
import json
import os
import tarfile
from typing import Any, Dict, List, Optional, Tuple

# Name of the manifest entry inside a `.kap` deliverable bundle.
_KAP_MANIFEST_NAME = "manifest.json"


def sha256_file(path: str) -> str:
    """Streaming SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_kap_bundle(
    out_dir: str,
    members: List[Tuple[str, str]],
    extra_manifest: Optional[Dict[str, Any]] = None,
    content_exclude: Tuple[str, ...] = (),
) -> str:
    """Write a `.kap` deliverable bundle (RFC 0013 §3): a gzip TAR archive named
    by the SHA-256 of its content.

    `members` is a list of ``(source_path, archive_name)``; missing paths are
    skipped. The bundle file name derives *only* from the digests of the
    content members (those whose archive name is not in `content_exclude`), so
    identical inputs produce the same `.kap` and build metadata in the manifest
    never moves it. TAR entry mtime/uid/gid are zeroed so the archive bytes are
    reproducible too (RFC 0012). Returns the bundle path.
    """
    present = [(p, a) for p, a in members if os.path.isfile(p)]
    digests = {a: sha256_file(p) for p, a in present}

    manifest: Dict[str, Any] = {
        "kap_version": "1.0",
        "artifacts": [{"name": a, "sha256": digests[a]} for _p, a in present],
    }
    if extra_manifest:
        manifest.update(extra_manifest)
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")

    content = sorted(
        (a, h) for a, h in digests.items() if a not in content_exclude
    )
    bundle_sha = hashlib.sha256(
        json.dumps(content, sort_keys=True).encode("utf-8")
    ).hexdigest()
    kap_path = os.path.join(out_dir, f"{bundle_sha[:16]}.kap")

    with tarfile.open(kap_path, "w:gz") as tar:
        mi = tarfile.TarInfo(_KAP_MANIFEST_NAME)
        mi.size = len(manifest_bytes)
        mi.mtime = 0
        tar.addfile(mi, io.BytesIO(manifest_bytes))
        for path, arcname in present:
            ti = tar.gettarinfo(path, arcname=arcname)
            ti.mtime = 0
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            with open(path, "rb") as fh:
                tar.addfile(ti, fh)
    return kap_path


def read_kap_bundle(kap_path: str) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
    """Return ``(manifest, {archive_name: bytes})`` for a `.kap` bundle written
    by :func:`write_kap_bundle`. The counterpart the archive never had."""
    files: Dict[str, bytes] = {}
    with tarfile.open(kap_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            extracted = tar.extractfile(member)
            if extracted is not None:
                files[member.name] = extracted.read()
    manifest = json.loads(files.pop(_KAP_MANIFEST_NAME, b"{}").decode("utf-8") or "{}")
    return manifest, files
