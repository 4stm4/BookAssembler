"""
Manager configuration (env-driven, RFC 0022 §5.4/§4.3).

All timeouts are seconds; defaults are safe for Kaggle free-tier T4 lifecycles.
"""

import os
from dataclasses import dataclass, field
from typing import List


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


def _env_list(name: str, default: List[str]) -> List[str]:
    v = os.environ.get(name)
    return [s.strip() for s in v.split(",") if s.strip()] if v else list(default)


@dataclass(frozen=True)
class ManagerConfig:
    # Public endpoint
    host: str = os.environ.get("KAE_MANAGER_HOST", "0.0.0.0")
    port: int = _env_int("KAE_MANAGER_PORT", 8080)

    # Auth (Bearer token)
    kae_token: str = os.environ.get("KAE_MANAGER_TOKEN", "")       # KAE → Manager
    runner_token: str = os.environ.get("KAE_RUNNER_TOKEN", "")     # Manager → Runner

    # Backend to (re)start the runner. Options: "kaggle" | "gh_actions" | "local" | "manual".
    # "manual": Manager never starts a runner itself; it just waits for /runner/announce.
    backend: str = os.environ.get("KAE_MANAGER_BACKEND", "manual")

    # Static Runner URL (if backend="manual" and no announce yet, we still probe this URL).
    runner_static_url: str = os.environ.get("KAE_RUNNER_URL", "")

    # Timeouts (RFC 0022 §5.3, §4.1)
    warmup_timeout: int = _env_int("KAE_MANAGER_WARMUP_TIMEOUT", 180)      # /ready wait
    infer_timeout: int = _env_int("KAE_MANAGER_INFER_TIMEOUT", 600)        # KAE-side long-poll
    idle_timeout: int = _env_int("KAE_MANAGER_IDLE_TIMEOUT", 900)          # runner-side (advisory)
    min_restart_interval: int = _env_int("KAE_MANAGER_MIN_RESTART_INTERVAL", 60)
    cooldown: int = _env_int("KAE_MANAGER_COOLDOWN", 120)

    # Queue / back-pressure
    max_queue: int = _env_int("KAE_MANAGER_MAX_QUEUE", 8)

    # Announce endpoint hardening (RFC 0022 §5.2)
    # `announce_allow_local`: accept loopback/private URLs (dev/tests only).
    announce_allow_local: bool = os.environ.get(
        "KAE_MANAGER_ANNOUNCE_ALLOW_LOCAL", "0") == "1"
    # Minimum seconds between accepted announce calls (rate limit against spam).
    announce_min_interval: int = _env_int("KAE_MANAGER_ANNOUNCE_MIN_INTERVAL", 2)

    # Roles this managed agent declares to KAE (surfaced in /health).
    roles: List[str] = field(default_factory=lambda: _env_list(
        "KAE_MANAGER_ROLES", ["table", "formula", "vision"],
    ))

    # Kaggle-backend specifics (used only when backend="kaggle").
    kaggle_kernel: str = os.environ.get("KAE_KAGGLE_KERNEL", "")           # "<user>/<slug>"
    kaggle_kernel_dir: str = os.environ.get("KAE_KAGGLE_KERNEL_DIR", "")   # local folder
