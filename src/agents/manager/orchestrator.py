"""
Runner lifecycle orchestration (RFC 0022 §5). Given a request, ensures the
Runner is up and /ready, then hands the request to the caller.

Not a queue by itself — a coordinator that other request handlers wait on.
"""

import asyncio
import logging
import time
from typing import Optional

from src.agents.manager.backends.base import RunnerBackend
from src.agents.manager.config import ManagerConfig
from src.agents.manager.runner_client import RunnerClient
from src.agents.manager.state import ManagerState, RunnerStatus

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, cfg: ManagerConfig, state: ManagerState, backend: RunnerBackend) -> None:
        self.cfg = cfg
        self.state = state
        self.backend = backend
        self._starting_lock = asyncio.Lock()  # only one concurrent start

    def client(self) -> Optional[RunnerClient]:
        if not self.state.runner_url:
            return None
        return RunnerClient(self.state.runner_url, token=self.cfg.runner_token)

    async def ensure_ready(self) -> RunnerClient:
        """Block until Runner is reachable and /ready; raise on hard failure."""
        # Fast path — an existing runner that answers /ready.
        cli = self.client()
        if cli and self.state.status == RunnerStatus.UP and await cli.ready():
            await self.state.mark_probe_ok()
            return cli

        # Otherwise probe once; may transition warming→up.
        if cli:
            if await cli.ready():
                await self.state.set_status(RunnerStatus.UP)
                await self.state.mark_probe_ok()
                return cli
            # Runner is announced but not ready → still warming.
            await self.state.set_status(RunnerStatus.WARMING)

        # If the runner is not known at all → try to start (rate-limited).
        if self.state.runner_url is None:
            await self._maybe_start()

        # Wait for readiness (announce + warmup) up to warmup_timeout.
        deadline = time.time() + self.cfg.warmup_timeout
        backoff = 0.5
        while time.time() < deadline:
            cli = self.client()
            if cli and await cli.ready():
                await self.state.set_status(RunnerStatus.UP)
                await self.state.mark_probe_ok()
                return cli
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 5.0)

        await self.state.set_status(RunnerStatus.ERROR, err="warmup timeout")
        raise TimeoutError("Runner did not become ready in time")

    async def _maybe_start(self) -> None:
        """Rate-limited backend.start() (RFC 0022 §5.4 MIN_RESTART_INTERVAL)."""
        async with self._starting_lock:
            now = time.time()
            since = now - self.state.last_restart_at
            if since < self.cfg.min_restart_interval:
                # Someone just tried; don't spam the backend.
                return
            await self.state.set_status(RunnerStatus.STARTING)
            try:
                hint = await self.backend.start()
                if hint:
                    await self.state.announce_runner(hint)
            except Exception as e:
                await self.state.set_status(RunnerStatus.ERROR, err=f"backend start: {e}")
                log.exception("backend.start failed")
                raise

    async def note_infer_error(self, err: str) -> None:
        """Called by the request path when a runner /infer fails."""
        # 3 consecutive infer errors → shutdown + cooldown (RFC 0022 §5.5).
        await self.state.set_status(RunnerStatus.ERROR, err=err)
        if self.state.consecutive_errors >= 3:
            log.warning("3+ infer errors — shutting down runner and cooling %ss",
                        self.cfg.cooldown)
            cli = self.client()
            if cli:
                await cli.shutdown()
            await self.state.set_status(RunnerStatus.STOPPING)
            await asyncio.sleep(self.cfg.cooldown)
            await self.state.set_status(RunnerStatus.COLD)
