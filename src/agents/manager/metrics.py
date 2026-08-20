"""
Prometheus-style metrics (RFC 0022 §7). Text exposition, no client library —
one function returns the payload.
"""

import time
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Metrics:
    started_at: float = field(default_factory=time.time)
    infer_total: int = 0
    infer_errors_total: int = 0
    backend_errors_total: int = 0
    auth_fail_total: int = 0
    announce_total: int = 0
    announce_rejected_total: int = 0
    queue_high_water: int = 0
    infer_duration_sum: float = 0.0     # seconds
    infer_duration_count: int = 0
    per_task: Dict[str, int] = field(default_factory=dict)

    def record_infer(self, task: str, duration: float, ok: bool) -> None:
        self.infer_total += 1
        self.infer_duration_sum += duration
        self.infer_duration_count += 1
        self.per_task[task] = self.per_task.get(task, 0) + 1
        if not ok:
            self.infer_errors_total += 1

    def observe_queue(self, depth: int) -> None:
        if depth > self.queue_high_water:
            self.queue_high_water = depth


def render(metrics: Metrics, gpu_seconds_used: float, queue_depth: int) -> str:
    """Prometheus text exposition."""
    up = time.time() - metrics.started_at
    avg = (metrics.infer_duration_sum / metrics.infer_duration_count
           if metrics.infer_duration_count else 0.0)
    lines = [
        f"# HELP kae_manager_up_seconds Manager uptime.",
        f"# TYPE kae_manager_up_seconds counter",
        f"kae_manager_up_seconds {up:.1f}",
        f"# HELP kae_gpu_seconds_used Cumulative GPU wall-time consumed by runner(s).",
        f"# TYPE kae_gpu_seconds_used counter",
        f"kae_gpu_seconds_used {gpu_seconds_used:.1f}",
        f"# HELP kae_infer_total Total /infer requests served.",
        f"# TYPE kae_infer_total counter",
        f"kae_infer_total {metrics.infer_total}",
        f"# HELP kae_infer_errors_total Total /infer failures (5xx/timeout).",
        f"# TYPE kae_infer_errors_total counter",
        f"kae_infer_errors_total {metrics.infer_errors_total}",
        f"# HELP kae_backend_errors_total Runner backend (Kaggle/etc) start failures.",
        f"# TYPE kae_backend_errors_total counter",
        f"kae_backend_errors_total {metrics.backend_errors_total}",
        f"# HELP kae_auth_fail_total Bearer/secret auth failures.",
        f"# TYPE kae_auth_fail_total counter",
        f"kae_auth_fail_total {metrics.auth_fail_total}",
        f"# HELP kae_announce_total /runner/announce calls (accepted or unchanged).",
        f"# TYPE kae_announce_total counter",
        f"kae_announce_total {metrics.announce_total}",
        f"# HELP kae_announce_rejected_total /runner/announce calls rejected (400/401/429).",
        f"# TYPE kae_announce_rejected_total counter",
        f"kae_announce_rejected_total {metrics.announce_rejected_total}",
        f"# HELP kae_infer_duration_avg_seconds Average end-to-end /infer duration.",
        f"# TYPE kae_infer_duration_avg_seconds gauge",
        f"kae_infer_duration_avg_seconds {avg:.3f}",
        f"# HELP kae_queue_depth Current pending /infer requests.",
        f"# TYPE kae_queue_depth gauge",
        f"kae_queue_depth {queue_depth}",
        f"# HELP kae_queue_high_water Peak pending /infer requests seen.",
        f"# TYPE kae_queue_high_water gauge",
        f"kae_queue_high_water {metrics.queue_high_water}",
    ]
    for task, n in sorted(metrics.per_task.items()):
        lines.append(f'kae_infer_task_total{{task="{task}"}} {n}')
    return "\n".join(lines) + "\n"
