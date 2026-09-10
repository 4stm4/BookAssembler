"""
OllamaBackend — edge-cluster backend that delegates inference to an ollama
instance (RFC 0022 §5.1, v1.1.0).

Unlike KaggleKernelBackend, ollama is always-on: start/stop are no-ops, and
status() probes the ollama HTTP API (/api/tags) to confirm the service is
reachable.

Config env vars:
    KAE_OLLAMA_HOST  — ollama base URL (default http://localhost:11434)
"""

import logging
import os
from typing import Optional

from src.agents.manager.backends.base import BackendStatus

log = logging.getLogger(__name__)

DEFAULT_OLLAMA_HOST = "http://localhost:11434"


class OllamaBackend:
    """RunnerBackend for an always-on ollama instance."""

    def __init__(self, host: Optional[str] = None) -> None:
        self.host = (host or os.environ.get("KAE_OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).rstrip("/")

    async def start(self) -> Optional[str]:
        log.info("OllamaBackend: start() is a no-op — ollama is always-on at %s", self.host)
        return self.host

    async def stop(self) -> None:
        log.info("OllamaBackend: stop() is a no-op — ollama lifecycle is managed externally")

    async def status(self) -> BackendStatus:
        try:
            import httpx
        except ImportError:
            return await self._status_urllib()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.host}/api/tags")
                if resp.status_code == 200:
                    return "up"
                log.warning("OllamaBackend: /api/tags returned %s", resp.status_code)
                return "error"
        except Exception as e:
            log.warning("OllamaBackend: probe failed: %s", e)
            return "cold"

    async def _status_urllib(self) -> BackendStatus:
        import asyncio
        import urllib.request
        import urllib.error

        def _probe() -> BackendStatus:
            try:
                req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        return "up"
                    return "error"
            except urllib.error.URLError:
                return "cold"
            except Exception:
                return "cold"

        return await asyncio.to_thread(_probe)
