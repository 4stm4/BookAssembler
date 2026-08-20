"""
RunnerBackend protocol + a Manual backend used when the operator starts the
Runner by hand (Kaggle "Run all" button). Real backends (Kaggle API, GH
Actions, local subprocess) implement the same protocol — see RFC 0022 §5.1.
"""

from typing import Literal, Optional, Protocol

BackendStatus = Literal["cold", "starting", "up", "error"]


class RunnerBackend(Protocol):
    """Contract every Runner-launch backend must satisfy."""

    async def start(self) -> Optional[str]:
        """Kick off a Runner. Return a hint URL if known synchronously, else None
        (the Runner will POST /runner/announce with its URL when it's up)."""
        ...

    async def stop(self) -> None:
        """Best-effort teardown of the Runner (kernel/kill/etc)."""
        ...

    async def status(self) -> BackendStatus:
        """Backend-level probe (kernel state), not the Runner's own /health."""
        ...


class ManualBackend:
    """No-op backend for the operator-managed case.

    Manager never starts a Runner itself; it waits for /runner/announce to
    receive a URL, or reuses `KAE_RUNNER_URL` if provided. Suitable for the
    early days when we start Kaggle notebooks by hand.
    """

    async def start(self) -> Optional[str]:
        return None

    async def stop(self) -> None:
        return None

    async def status(self) -> BackendStatus:
        return "cold"
