"""
Runner backends — pluggable adapters that (re)start the GPU Runner process
(RFC 0022 §5.1). All backends must satisfy the RunnerBackend Protocol.
"""

from src.agents.manager.backends.base import ManualBackend, RunnerBackend

__all__ = ["RunnerBackend", "ManualBackend"]
