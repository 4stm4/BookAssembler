"""
KaggleKernelBackend — starts the Runner via Kaggle notebook API (RFC 0022 §5.1).

Workflow:
    1. `start()` bumps a new version of a Kaggle notebook that boots the Runner
       (`python -m src.agents.runner`) and exposes it via a cloudflared tunnel.
       Kaggle enqueues the kernel; we return without waiting for readiness —
       Manager's orchestrator polls /ready itself, and the Runner will POST
       /runner/announce once cloudflared is up (RFC 0022 §5.2).
    2. `status()` maps Kaggle kernel status → BackendStatus.
    3. `stop()` is a documented no-op: Kaggle has no public "kill kernel" API;
       we rely on Runner's idle self-shutdown (RFC 0022 §5.4 + §9.4).

Auth: uses standard Kaggle credentials — ~/.kaggle/kaggle.json OR
KAGGLE_USERNAME + KAGGLE_KEY env vars (Kaggle's own convention). If neither is
present or the `kaggle` package isn't installed, initialization fails fast so
we never silently fall back and mask a config error.

The `kaggle` package is an OPTIONAL runtime dep. It's imported lazily so unit
tests can inject a fake API without needing the real package on the test host.
"""

import logging
import os
from typing import Any, Optional

from src.agents.manager.backends.base import BackendStatus

log = logging.getLogger(__name__)

# Map of Kaggle kernel statuses (lowercase strings from the API) to our states.
# See: kernels_status().status values in the Kaggle Python client.
_KAGGLE_TO_BACKEND: dict = {
    "queued": "starting",
    "running": "up",              # kernel is executing our runner
    "complete": "cold",           # kernel finished (our runner exited normally)
    "cancelled": "cold",
    "cancelrequested": "cold",
    "cancelacknowledged": "cold",
    "error": "error",
    "failed": "error",
}


class KaggleKernelBackend:
    """RunnerBackend using the Kaggle Kernels API.

    Args:
        kernel: "<owner>/<slug>", e.g. "youruser/kae-runner".
        kernel_dir: local directory containing the kernel's files
            (kernel-metadata.json + notebook). Only needed for start().
        api: optional injected API object (for tests). If None, the real
            KaggleApi is created and authenticated at construction time.
    """

    def __init__(self, kernel: str, kernel_dir: str = "", api: Optional[Any] = None) -> None:
        if not kernel or "/" not in kernel:
            raise ValueError("kernel must be '<owner>/<slug>'")
        self.kernel = kernel
        self.kernel_dir = kernel_dir or ""
        if api is not None:
            self._api = api
        else:
            self._api = self._make_api()

    @staticmethod
    def _make_api() -> Any:
        try:
            from kaggle.api.kaggle_api_extended import KaggleApi  # type: ignore
        except Exception as e:  # ImportError or ~/.kaggle/kaggle.json parse errors
            raise RuntimeError(
                "KaggleKernelBackend requires the `kaggle` package and "
                "Kaggle credentials (~/.kaggle/kaggle.json or KAGGLE_USERNAME+KAGGLE_KEY)"
            ) from e
        api = KaggleApi()
        api.authenticate()  # raises IOError if creds missing
        return api

    async def start(self) -> Optional[str]:
        """Push a new kernel version — Kaggle enqueues and runs it."""
        if not self.kernel_dir or not os.path.isdir(self.kernel_dir):
            raise RuntimeError(
                f"kernel_dir '{self.kernel_dir}' does not exist; "
                "cannot push kernel (set KAE_KAGGLE_KERNEL_DIR)"
            )
        # kernels_push_cli takes the folder path and reads kernel-metadata.json
        # inside it — the same layout `kaggle kernels init` produces.
        log.info("Kaggle: pushing kernel %s from %s", self.kernel, self.kernel_dir)
        # NB: kernels_push_cli is sync/blocking; run it in a worker thread so
        # we don't block the Manager's event loop.
        import asyncio
        await asyncio.to_thread(self._api.kernels_push_cli, self.kernel_dir)
        return None  # URL comes back via /runner/announce (RFC 0022 §5.2)

    async def stop(self) -> None:
        # Kaggle exposes no public "cancel kernel" endpoint; the Runner
        # self-terminates on idle (RFC 0022 §5.4). Log so operator can inspect.
        log.info("Kaggle: stop() is a no-op — Runner self-shuts down on idle")

    async def status(self) -> BackendStatus:
        try:
            owner, slug = self.kernel.split("/", 1)
            import asyncio
            resp = await asyncio.to_thread(self._api.kernels_status, owner, slug)
        except Exception as e:
            log.warning("Kaggle status() failed: %s", e)
            return "error"
        # kaggle-api returns an object with .status (str). Normalise defensively.
        raw = getattr(resp, "status", None) or (
            resp.get("status") if isinstance(resp, dict) else None
        )
        key = (raw or "").strip().lower()
        return _KAGGLE_TO_BACKEND.get(key, "error")
