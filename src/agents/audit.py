"""
Audit log for GPU Runner Manager/Runner (RFC 0022 §7, format from RFC 0020).

Thin wrapper around src.audit.logger.AuditLogger with:
- default log path per component (KAE_MANAGER_STATE_DIR / KAE_RUNNER_STATE_DIR);
- typed event helpers so callers don't hand-craft the details dict;
- a no-op fallback when writing to disk would fail (read-only FS on Kaggle
  scratch), because an audit hiccup must never break /infer.
"""

import logging
import os
from typing import Any, Dict, Optional

from src.audit.logger import AuditLogger

log = logging.getLogger(__name__)


def _dir_for(component: str) -> str:
    env = f"KAE_{component.upper()}_STATE_DIR"
    return os.environ.get(env, os.path.join(os.getcwd(), f".{component}"))


class AgentAudit:
    """Component-scoped audit logger. `component` ∈ {'manager','runner'}."""

    def __init__(self, component: str, actor: Optional[str] = None,
                 log_dir: Optional[str] = None) -> None:
        self.component = component
        self.actor = actor or component
        self._logger: Optional[AuditLogger]
        try:
            self._logger = AuditLogger(log_dir or _dir_for(component))
        except Exception as e:
            log.warning("audit disabled (cannot open log dir): %s", e)
            self._logger = None

    def _emit(self, event_type: str, **details: Any) -> None:
        if self._logger is None:
            return
        try:
            self._logger.log(event_type, self.actor, {k: v for k, v in details.items()
                                                     if v is not None})
        except Exception as e:  # never let audit crash the caller
            log.warning("audit write failed (%s): %s", event_type, e)

    # ---- Manager events ----
    def manager_started(self, cfg: Dict[str, Any]) -> None:
        self._emit("MANAGER_STARTED", cfg=cfg)

    def runner_announced(self, url: str, status: str, replaced: Optional[str] = None) -> None:
        self._emit("RUNNER_ANNOUNCED", url=url, status=status, replaced=replaced)

    def runner_start_requested(self, backend: str) -> None:
        self._emit("RUNNER_START_REQUESTED", backend=backend)

    def runner_stopped(self, reason: str) -> None:
        self._emit("RUNNER_STOPPED", reason=reason)

    def runner_error(self, err: str) -> None:
        self._emit("RUNNER_ERROR", error=err)

    def auth_failed(self, path: str, reason: str) -> None:
        self._emit("AUTH_FAILED", path=path, reason=reason)

    def infer_completed(self, task: str, duration_ms: int, bytes_in: int) -> None:
        self._emit("INFER_COMPLETED", task=task,
                   duration_ms=duration_ms, bytes_in=bytes_in)

    def infer_failed(self, task: str, err: str) -> None:
        self._emit("INFER_FAILED", task=task, error=err)

    # ---- Runner events ----
    def runner_started(self, warmup: list) -> None:
        self._emit("RUNNER_STARTED", warmup=warmup)

    def model_loaded(self, name: str, vram_mb: int) -> None:
        self._emit("MODEL_LOADED", name=name, vram_mb=vram_mb)

    def model_unloaded(self, name: str, reason: str) -> None:
        self._emit("MODEL_UNLOADED", name=name, reason=reason)

    def idle_exit(self, idle_seconds: float) -> None:
        self._emit("IDLE_EXIT", idle_seconds=round(idle_seconds, 1))
