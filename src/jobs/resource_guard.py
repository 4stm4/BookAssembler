"""Runtime memory guardrail (RFC 0019 §3).

Heavy stages — full analyzer pipeline, XeLaTeX, local LLM inference — can push a
constrained host (rpi5 / 3 GB Docker) into swap or an OOM kill. RFC 0019 §3
gates new work at 85% RAM: over the line, workers are "throttled and queued
until system resources free up".

`psutil` is used when installed; otherwise `/proc/meminfo` on Linux; otherwise
the guard is a no-op (dev machines without either), so this never blocks a
platform it cannot measure.
"""

import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


def _ram_percent() -> Optional[float]:
    """Percent of physical RAM in use, or None if it cannot be measured."""
    try:
        import psutil  # type: ignore[import-untyped]

        return float(psutil.virtual_memory().percent)
    except Exception:
        pass
    try:
        meminfo = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                meminfo[key.strip()] = float(rest.strip().split()[0])  # kB
        total = meminfo.get("MemTotal", 0.0)
        available = meminfo.get(
            "MemAvailable",
            meminfo.get("MemFree", 0.0) + meminfo.get("Cached", 0.0),
        )
        if total > 0:
            return (1.0 - available / total) * 100.0
    except Exception:
        pass
    return None


class ResourceGuard:
    """RFC 0019 §3 memory guardrail."""

    MAX_RAM_PERCENT = 85.0

    @classmethod
    def check_memory_available(cls) -> bool:
        """True when RAM headroom is below the threshold, or unmeasurable."""
        pct = _ram_percent()
        return pct is None or pct < cls.MAX_RAM_PERCENT

    @classmethod
    async def wait_for_memory(
        cls, timeout: float = 120.0, poll: float = 3.0,
    ) -> bool:
        """Block until memory is available or `timeout` elapses.

        Returns True if it became available, False if the wait timed out (the
        caller proceeds anyway — refusing the job outright is worse than a slow
        one, and the measurement may be pessimistic)."""
        deadline = time.monotonic() + timeout
        waited = False
        while not cls.check_memory_available():
            if time.monotonic() >= deadline:
                log.warning(
                    "ResourceGuard: RAM still >%.0f%% after %.0fs; proceeding anyway",
                    cls.MAX_RAM_PERCENT, timeout,
                )
                return False
            if not waited:
                log.info(
                    "ResourceGuard: RAM >%.0f%%, holding new work until it frees",
                    cls.MAX_RAM_PERCENT,
                )
                waited = True
            await asyncio.sleep(poll)
        return True
