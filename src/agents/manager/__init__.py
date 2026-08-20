"""
GPU Runner Manager (RFC 0022).

Always-on CPU-side service that exposes /health + /infer to KAE, orchestrates
the GPU Runner lifecycle (cold → warming → up → cooling), and enforces auth,
back-pressure, rate limits and metrics.
"""

from src.agents.manager.state import ManagerState, RunnerStatus

__all__ = ["ManagerState", "RunnerStatus"]
