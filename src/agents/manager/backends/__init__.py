"""
Runner backends — pluggable adapters that (re)start the GPU Runner process
(RFC 0022 §5.1). All backends must satisfy the RunnerBackend Protocol.
"""

from src.agents.manager.backends.base import ManualBackend, RunnerBackend
from src.agents.manager.backends.ollama import OllamaBackend

__all__ = ["RunnerBackend", "ManualBackend", "OllamaBackend"]
