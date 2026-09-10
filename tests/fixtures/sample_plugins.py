"""Plugin stubs executed inside the sandbox by tests (RFC 0010 §4.2).

These live in an importable module because the sandbox spawns a fresh interpreter
and imports the entry point by dotted path.
"""

import os
import time
from typing import Any, Dict


class EchoPlugin:
    def run_sandboxed(self, doc_state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "applied_mutations": [
                {
                    "op": "add_kg_entity",
                    "entity": {
                        "id": "ent_benzene_01",
                        "name": doc_state.get("title", "Benzene Ring"),
                        "entity_type": "concept_term",
                    },
                }
            ]
        }


class RaisingPlugin:
    def run_sandboxed(self, doc_state: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("plugin blew up")


class CrashingPlugin:
    """Dies the way a segfaulting C extension would — no chance to report back."""

    def run_sandboxed(self, doc_state: Dict[str, Any]) -> Dict[str, Any]:
        os._exit(139)


class HangingPlugin:
    def run_sandboxed(self, doc_state: Dict[str, Any]) -> Dict[str, Any]:
        time.sleep(120)
        return {}


class MemoryHogPlugin:
    def run_sandboxed(self, doc_state: Dict[str, Any]) -> Dict[str, Any]:
        blocks = []
        for _ in range(64):
            blocks.append(bytearray(64 * 1024 * 1024))
        return {}


class NetworkPlugin:
    def run_sandboxed(self, doc_state: Dict[str, Any]) -> Dict[str, Any]:
        import socket

        socket.socket()
        return {}


class NotADeltaPlugin:
    def run_sandboxed(self, doc_state: Dict[str, Any]) -> Any:
        return "definitely not a delta"
