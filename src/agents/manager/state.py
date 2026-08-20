"""
Runner state machine + shared Manager state (RFC 0022 §5.5).

Thread-safe wrapper around the current Runner URL, health status, and lifecycle
counters. The transitions are intentionally simple — the source of truth is the
last successful probe / announce; this object memoizes them for the queue/API.
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RunnerStatus(str, Enum):
    COLD = "cold"          # nothing running; we may start it on demand
    STARTING = "starting"  # backend.start() issued, waiting for announce/health
    WARMING = "warming"    # HTTP alive, but /ready still 503 (loading models)
    UP = "up"              # /ready OK
    ERROR = "error"        # repeated 5xx / probe failed; cooling before restart
    STOPPING = "stopping"  # /shutdown issued


@dataclass
class ManagerState:
    status: RunnerStatus = RunnerStatus.COLD
    runner_url: Optional[str] = None
    last_probe_ok_at: float = 0.0
    last_infer_ok_at: float = 0.0
    last_restart_at: float = 0.0
    last_error: Optional[str] = None
    consecutive_errors: int = 0
    # Cumulative uptime across runner lives, seconds. Increment on successful stop.
    gpu_seconds_used: float = 0.0
    _current_up_since: Optional[float] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def set_status(self, status: RunnerStatus, err: Optional[str] = None) -> None:
        async with self.lock:
            prev = self.status
            self.status = status
            if err:
                self.last_error = err
                self.consecutive_errors += 1
            else:
                self.consecutive_errors = 0

            now = time.time()
            # Track "runner up" wall-time for gpu_minutes_used accounting.
            if status == RunnerStatus.UP and self._current_up_since is None:
                self._current_up_since = now
            elif status in (RunnerStatus.COLD, RunnerStatus.STOPPING, RunnerStatus.ERROR):
                if self._current_up_since is not None:
                    self.gpu_seconds_used += now - self._current_up_since
                    self._current_up_since = None
            if prev != status and status == RunnerStatus.STARTING:
                self.last_restart_at = now

    async def announce_runner(self, url: str) -> None:
        async with self.lock:
            self.runner_url = url

    async def mark_probe_ok(self) -> None:
        async with self.lock:
            self.last_probe_ok_at = time.time()

    async def mark_infer_ok(self) -> None:
        async with self.lock:
            self.last_infer_ok_at = time.time()

    def snapshot_gpu_seconds(self) -> float:
        """Read cumulative GPU seconds, including the ongoing run if any."""
        base = self.gpu_seconds_used
        if self._current_up_since is not None:
            base += time.time() - self._current_up_since
        return base
