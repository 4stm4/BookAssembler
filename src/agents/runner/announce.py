"""
Push discovery (RFC 0022 §5.2). On startup the Runner POSTs its public URL
to the Manager so the Manager doesn't have to scrape logs or poll Kaggle.
"""

import asyncio
import json
import logging
import urllib.request

log = logging.getLogger(__name__)


async def announce_to_manager(manager_url: str, public_url: str, secret: str,
                              timeout: float = 10.0) -> bool:
    """POST /runner/announce {url, secret}. Returns True on 2xx."""
    if not manager_url or not public_url:
        return False
    body = json.dumps({"url": public_url, "secret": secret}).encode()
    req = urllib.request.Request(
        f"{manager_url.rstrip('/')}/runner/announce",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    def _do() -> bool:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return 200 <= r.status < 300
        except Exception as e:
            log.warning("announce failed: %s", e)
            return False

    return await asyncio.to_thread(_do)
