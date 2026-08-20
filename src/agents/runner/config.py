"""
Runner configuration (RFC 0022 §6).

All fields env-driven so the Kaggle notebook only needs `python -m
src.agents.runner`; overrides go in the shell/notebook cell.
"""

import os
from dataclasses import dataclass, field
from typing import List


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_list(name: str, default: List[str]) -> List[str]:
    v = os.environ.get(name)
    return [s.strip() for s in v.split(",") if s.strip()] if v else list(default)


@dataclass(frozen=True)
class RunnerConfig:
    host: str = os.environ.get("KAE_RUNNER_HOST", "0.0.0.0")
    port: int = _env_int("KAE_RUNNER_PORT", 5005)

    # Shared secret with Manager (Bearer) — protects the public tunnel.
    token: str = os.environ.get("KAE_RUNNER_TOKEN", "")

    # Manager to which we PUSH our URL at startup (RFC 0022 §5.2).
    manager_url: str = os.environ.get("KAE_MANAGER_URL", "")
    # Our own public URL (cloudflared or similar); passed by the notebook once known.
    public_url: str = os.environ.get("KAE_RUNNER_PUBLIC_URL", "")

    # Which task loaders to prewarm so /ready flips quickly (see loaders/).
    warmup_tasks: List[str] = field(default_factory=lambda: _env_list(
        "KAE_RUNNER_WARMUP_TASKS", ["vision"],
    ))

    # Idle shutdown (RFC 0022 §5.4). Set to 0 to disable (dev only — INVARIANT §9.4).
    idle_timeout: int = _env_int("KAE_RUNNER_IDLE_TIMEOUT", 900)

    # LRU model pool budget in MB; 0 → auto (detect free VRAM on start).
    vram_budget_mb: int = _env_int("KAE_RUNNER_VRAM_BUDGET_MB", 0)
