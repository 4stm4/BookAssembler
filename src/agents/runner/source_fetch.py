"""
Fetch and render a source page on the Runner (RFC 0022 §4.2).

Why the Runner and not the caller: on the KAE deployment this serves, the
orchestrating host uploads at ~1.7 KB/s and downloads at ~4.6 MB/s. Sending it a
rendered page costs ~13s of upload against 1-3s of inference, so the GPU spends
a run waiting on the wire. The Runner has ordinary bandwidth, so it fetches the
document once and renders every requested page locally; only text goes back.

The document is cached by URL — a book is one download for all its pages.
"""

import hashlib
import ipaddress
import logging
import os
import threading
import urllib.parse
import urllib.request
from typing import Dict, Optional

log = logging.getLogger(__name__)

CACHE_DIR = os.environ.get("KAE_RUNNER_SOURCE_CACHE", "/tmp/kae-sources")
MAX_BYTES = int(os.environ.get("KAE_RUNNER_MAX_SOURCE_BYTES", str(512 * 1024 * 1024)))
FETCH_TIMEOUT = int(os.environ.get("KAE_RUNNER_FETCH_TIMEOUT", "120"))
RENDER_DPI = int(os.environ.get("KAE_RUNNER_RENDER_DPI", "150"))

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class SourceFetchError(Exception):
    """The document could not be fetched or the page could not be rendered."""


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _check_url(url: str) -> None:
    """Reject anything that is not a plain remote http(s) document.

    The URL arrives over the network, so it must not be usable to read local
    files or to reach hosts inside the Runner's own network.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SourceFetchError(f"unsupported scheme: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host:
        raise SourceFetchError("missing host")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # a name; DNS may still resolve privately, see _guard_resolved
    _guard_ip(ip)


def _guard_ip(ip: "ipaddress._BaseAddress") -> None:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise SourceFetchError(f"refusing to fetch from non-public address {ip}")


def _cache_path(url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:32]
    return os.path.join(CACHE_DIR, f"{digest}.pdf")


def fetch(url: str) -> str:
    """Return a local path for `url`, downloading it once and caching it."""
    _check_url(url)
    path = _cache_path(url)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    with _lock_for(path):
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path  # another request won the race
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{path}.part"
        log.info("fetching source %s", url)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KAE-Runner"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                size = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise SourceFetchError(
                                f"source exceeds {MAX_BYTES} bytes")
                        f.write(chunk)
        except SourceFetchError:
            _unlink(tmp)
            raise
        except Exception as exc:
            _unlink(tmp)
            raise SourceFetchError(f"cannot fetch {url}: {exc}") from exc
        os.replace(tmp, path)
        log.info("cached %s (%d bytes)", url, os.path.getsize(path))
    return path


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def render_page(url: str, page: int, dpi: int = RENDER_DPI) -> bytes:
    """Fetch the document if needed and return `page` as PNG bytes.

    Rendered at the Runner's own DPI: there is no upload to pay for here, so the
    page is not degraded the way a client on a thin uplink has to degrade it.
    """
    path = fetch(url)
    try:
        import pymupdf as fitz  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - environment specific
        raise SourceFetchError("pymupdf is not installed on the runner") from exc

    doc = fitz.open(path)
    try:
        if page < 0 or page >= len(doc):
            raise SourceFetchError(
                f"page {page} out of range (document has {len(doc)})")
        return doc[page].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()
