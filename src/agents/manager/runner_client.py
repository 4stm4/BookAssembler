"""
Thin async HTTP client to the Runner (RFC 0022 §4.2). Uses stdlib urllib so we
have no extra runtime deps beyond FastAPI.
"""

import asyncio
import base64
import json
import logging
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class RunnerClient:
    def __init__(self, url: str, token: str = "") -> None:
        self.url = url.rstrip("/")
        self.token = token

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _request(self, method: str, path: str, body: Optional[dict] = None,
                       timeout: float = 30.0) -> Dict[str, Any]:
        def _do() -> Dict[str, Any]:
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(
                f"{self.url}{path}", data=data, method=method, headers=self._headers(),
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}

        return await asyncio.to_thread(_do)

    async def health(self, timeout: float = 5.0) -> Dict[str, Any]:
        return await self._request("GET", "/health", timeout=timeout)

    async def ready(self, timeout: float = 5.0) -> bool:
        try:
            await self._request("GET", "/ready", timeout=timeout)
            return True
        except Exception:
            return False

    async def infer(self, image_png: Optional[bytes], task: str,
                    prompt: Optional[str] = None, timeout: float = 300.0) -> str:
        body: Dict[str, Any] = {"task": task}
        # RFC 0022 §4.4: image_b64 only for image tasks. refine/translate
        # carry no image, and base64-encoding None crashed every text task
        # that reached this client — this is that seam.
        if image_png is not None:
            body["image_b64"] = base64.b64encode(image_png).decode()
        if prompt is not None:
            body["prompt"] = prompt
        resp = await self._request("POST", "/infer", body=body, timeout=timeout)
        return resp.get("text", "")

    async def shutdown(self) -> None:
        try:
            await self._request("POST", "/shutdown", body={}, timeout=5.0)
        except Exception as e:
            log.info("Runner shutdown request failed (may already be down): %s", e)
