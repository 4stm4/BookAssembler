"""
Idle watchdog (RFC 0022 §5.4 + §9.4 invariant).

When enabled, terminates the process after `idle_timeout` seconds without a
successful /infer request. On Kaggle this ends the kernel and stops burning
GPU-hours. Disabling (timeout=0) is dev-only.
"""

import asyncio
import logging
import os
import time
from typing import Callable

log = logging.getLogger(__name__)


async def run_watchdog(
    idle_timeout: int,
    get_last_request_ts: Callable[[], float],
    is_busy: Callable[[], bool],
    check_interval: float = 30.0,
    _exit: Callable[[int], None] = os._exit,
) -> None:
    """Background task; returns only if idle_timeout <= 0 (disabled)."""
    if idle_timeout <= 0:
        log.warning("Idle watchdog DISABLED (dev only — RFC 0022 §9.4)")
        return
    log.info("Idle watchdog: exit after %ss without traffic", idle_timeout)
    while True:
        await asyncio.sleep(check_interval)
        if is_busy():
            continue
        idle = time.time() - get_last_request_ts()
        if idle >= idle_timeout:
            log.warning("Idle %.0fs ≥ %ss — shutting down runner (os._exit)",
                        idle, idle_timeout)
            _exit(0)
