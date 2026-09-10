"""
Push discovery (RFC 0022 §5.2). On startup the Runner POSTs its public URL
to the Manager so the Manager doesn't have to scrape logs or poll Kaggle.

Retries with exponential backoff, because the Manager may be briefly
unreachable when a Runner boots (Kaggle cold-start races Manager restarts).
Also retries on Manager's 429 rate-limit response.
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


def _post_once(url: str, body: bytes, timeout: float) -> int:
    """Return HTTP status, or 0 on network-level failure."""
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return int(getattr(r, "status", 200))
    except urllib.error.HTTPError as e:
        return int(e.code)
    except Exception as e:
        log.warning("announce network error: %s", e)
        return 0


async def announce_to_manager(
    manager_url: str,
    public_url: str,
    secret: str,
    timeout: float = 10.0,
    max_attempts: int = 6,
    initial_backoff: float = 1.0,
) -> bool:
    """POST /runner/announce {url, secret}. Returns True on 2xx.

    Retry policy: exponential backoff (1s, 2s, 4s, ...) capped at 30s per attempt,
    stops on 2xx (success) or 4xx that isn't 429 (unrecoverable — bad URL/secret).
    """
    if not manager_url or not public_url:
        return False
    url = f"{manager_url.rstrip('/')}/runner/announce"
    body = json.dumps({"url": public_url, "secret": secret}).encode()

    backoff = initial_backoff
    for attempt in range(1, max_attempts + 1):
        status = await asyncio.to_thread(_post_once, url, body, timeout)
        if 200 <= status < 300:
            log.info("announce ok on attempt %d (status=%d)", attempt, status)
            return True
        # 4xx that's not 429 → don't hammer, we're misconfigured.
        if 400 <= status < 500 and status != 429:
            log.error("announce rejected (status=%d) — giving up", status)
            return False
        if attempt == max_attempts:
            break
        sleep_for = min(backoff, 30.0)
        log.warning("announce attempt %d failed (status=%d); retrying in %.1fs",
                    attempt, status, sleep_for)
        await asyncio.sleep(sleep_for)
        backoff *= 2

    log.error("announce failed after %d attempts", max_attempts)
    return False
