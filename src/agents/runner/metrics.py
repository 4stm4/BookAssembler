"""
Prometheus-style metrics for the Runner (RFC 0022 §7).
Text-format exposition, no client library — one function returns the payload.
"""

import time
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class RunnerMetrics:
    started_at: float = field(default_factory=time.time)
    infer_total: int = 0
    infer_errors_total: int = 0
    infer_duration_sum: float = 0.0
    infer_duration_count: int = 0
    per_task: Dict[str, int] = field(default_factory=dict)
    model_loads_total: int = 0
    model_unloads_total: int = 0

    def record_infer(self, task: str, duration: float, ok: bool) -> None:
        self.infer_total += 1
        self.infer_duration_sum += duration
        self.infer_duration_count += 1
        self.per_task[task] = self.per_task.get(task, 0) + 1
        if not ok:
            self.infer_errors_total += 1


def render(m: RunnerMetrics, models_loaded: list, vram_used_mb: int) -> str:
    up = time.time() - m.started_at
    avg = (m.infer_duration_sum / m.infer_duration_count
           if m.infer_duration_count else 0.0)
    lines = [
        "# HELP kae_runner_up_seconds Runner uptime.",
        "# TYPE kae_runner_up_seconds counter",
        f"kae_runner_up_seconds {up:.1f}",
        "# HELP kae_runner_vram_used_mb Approximate VRAM used by loaded models.",
        "# TYPE kae_runner_vram_used_mb gauge",
        f"kae_runner_vram_used_mb {vram_used_mb}",
        "# HELP kae_runner_infer_total Total /infer requests served.",
        "# TYPE kae_runner_infer_total counter",
        f"kae_runner_infer_total {m.infer_total}",
        "# HELP kae_runner_infer_errors_total /infer failures.",
        "# TYPE kae_runner_infer_errors_total counter",
        f"kae_runner_infer_errors_total {m.infer_errors_total}",
        "# HELP kae_runner_infer_duration_avg_seconds Average /infer duration.",
        "# TYPE kae_runner_infer_duration_avg_seconds gauge",
        f"kae_runner_infer_duration_avg_seconds {avg:.3f}",
        "# HELP kae_runner_model_loads_total Model .load() calls (incl. warmup).",
        "# TYPE kae_runner_model_loads_total counter",
        f"kae_runner_model_loads_total {m.model_loads_total}",
        "# HELP kae_runner_model_unloads_total Model .unload() calls (LRU evictions).",
        "# TYPE kae_runner_model_unloads_total counter",
        f"kae_runner_model_unloads_total {m.model_unloads_total}",
    ]
    for name in models_loaded:
        lines.append(f'kae_runner_model_loaded{{name="{name}"}} 1')
    for task, n in sorted(m.per_task.items()):
        lines.append(f'kae_runner_infer_task_total{{task="{task}"}} {n}')
    return "\n".join(lines) + "\n"
