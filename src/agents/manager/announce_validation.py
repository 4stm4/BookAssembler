"""
URL validation for the /runner/announce endpoint (RFC 0022 §5.2).

Rules:
  - scheme must be http or https;
  - host must be a resolvable name or a public IP (not loopback / private / link-local);
  - port must be in [1, 65535] or absent (defaults are fine).

Loopback/private hosts are rejected because a legitimate Runner announces its
PUBLIC tunnel (e.g. *.trycloudflare.com). Accepting private hosts would let
anyone with the shared secret trick the Manager into calling internal endpoints.
Loopback is allowed only when `allow_local=True` — that's how tests run.
"""

import ipaddress
from urllib.parse import urlparse


class AnnounceUrlError(ValueError):
    """Raised when the announced URL fails validation."""


def validate_runner_url(url: str, *, allow_local: bool = False) -> str:
    """Return the normalised URL or raise AnnounceUrlError."""
    if not isinstance(url, str) or not url:
        raise AnnounceUrlError("url is empty")

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise AnnounceUrlError(f"scheme must be http/https, got {parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise AnnounceUrlError("url has no host")

    # Numeric IP → block loopback/private/link-local/multicast unless explicitly allowed.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if not allow_local and (ip.is_loopback or ip.is_private
                                or ip.is_link_local or ip.is_multicast
                                or ip.is_reserved or ip.is_unspecified):
            raise AnnounceUrlError(f"non-public host not allowed: {host}")
    else:
        # Textual host — reject explicit localhost / .local unless allowed.
        low = host.lower()
        if not allow_local and (low == "localhost" or low.endswith(".local")):
            raise AnnounceUrlError(f"non-public host not allowed: {host}")

    if parsed.port is not None and not (1 <= parsed.port <= 65535):
        raise AnnounceUrlError(f"invalid port: {parsed.port}")

    # Strip trailing slash / query / fragment — the Runner endpoint contract
    # only uses the origin.
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin
