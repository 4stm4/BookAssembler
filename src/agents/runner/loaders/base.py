"""
ModelLoader contract (RFC 0022 §6). Each loader owns exactly one model; it
knows what tasks it can serve, how much VRAM it needs, and how to run inference.
"""

from typing import List, Optional, Protocol


class ModelLoader(Protocol):
    name: str            # model identity, e.g. "Qwen2.5-VL-7B"
    tasks: List[str]     # tasks this loader can serve, e.g. ["table","formula","vision"]
    vram_mb: int         # steady-state VRAM footprint (approx)
    loaded: bool         # True once .load() has completed

    async def load(self) -> None: ...
    async def unload(self) -> None: ...
    async def infer(self, image_png: bytes, task: str,
                    prompt: Optional[str] = None) -> str: ...


class EchoLoader:
    """Zero-dep loader for tests/dev. Returns a debug string; no GPU touched."""

    def __init__(self, name: str = "echo", tasks: Optional[List[str]] = None,
                 vram_mb: int = 0) -> None:
        self.name = name
        self.tasks = tasks or ["table", "formula", "vision"]
        self.vram_mb = vram_mb
        self.loaded = False

    async def load(self) -> None:
        self.loaded = True

    async def unload(self) -> None:
        self.loaded = False

    async def infer(self, image_png: bytes, task: str,
                    prompt: Optional[str] = None) -> str:
        # Deterministic echo — used by tests to assert routing.
        return f"echo({self.name}):{task}:{len(image_png)}"
