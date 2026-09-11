"""
ModelPool with LRU eviction by VRAM (RFC 0022 §6).

Registers loaders by task; loads lazily on first /infer for that task; evicts
the least-recently-used loader when a new load would exceed the VRAM budget.

Concurrency: serialized inside the pool — one active inference at a time on
the Runner (`_infer_lock`), and loading under a lock of its own (`_lock`), so
/health etc. stay responsive during long inferences. Concurrent inference on a
single GPU rarely helps and often OOMs; if we ever need it, that's a separate
RFC.
"""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.agents.runner.loaders.base import ModelLoader

log = logging.getLogger(__name__)


class Abandoned(Exception):
    """The caller left while its request waited for its turn."""


class ModelPool:
    def __init__(self, vram_budget_mb: int = 0) -> None:
        self.vram_budget_mb = vram_budget_mb  # 0 → no eviction (dev / tests)
        self._by_task: Dict[str, ModelLoader] = {}       # task → loader
        self._loaders: Dict[str, ModelLoader] = {}       # loader.name → loader
        self._last_used: Dict[str, float] = {}           # loader.name → ts
        self._lock = asyncio.Lock()
        self._infer_lock = asyncio.Lock()

    def register(self, loader: ModelLoader) -> None:
        for task in loader.tasks:
            if task in self._by_task and self._by_task[task] is not loader:
                raise ValueError(
                    f"task '{task}' already registered to loader "
                    f"'{self._by_task[task].name}', cannot rebind to '{loader.name}'"
                )
            self._by_task[task] = loader
        self._loaders[loader.name] = loader

    def tasks(self) -> List[str]:
        return sorted(self._by_task.keys())

    def loaded_names(self) -> List[str]:
        return sorted(name for name, ldr in self._loaders.items() if ldr.loaded)

    def vram_used_mb(self) -> int:
        return sum(ldr.vram_mb for ldr in self._loaders.values() if ldr.loaded)

    async def ensure_loaded(self, task: str) -> ModelLoader:
        """Return a loaded loader for `task`, loading + evicting as needed."""
        if task not in self._by_task:
            raise KeyError(f"unknown task: {task}")
        loader = self._by_task[task]
        async with self._lock:
            if loader.loaded:
                self._last_used[loader.name] = time.time()
                return loader

            # Make room if a VRAM budget is set.
            if self.vram_budget_mb > 0:
                await self._evict_for(loader)

            log.info("ModelPool: loading %s (vram=%dMB)", loader.name, loader.vram_mb)
            t0 = time.time()
            await loader.load()
            log.info("ModelPool: %s loaded in %.1fs", loader.name, time.time() - t0)
            self._last_used[loader.name] = time.time()
            return loader

    async def _evict_for(self, incoming: ModelLoader) -> None:
        need = incoming.vram_mb
        while self.vram_used_mb() + need > self.vram_budget_mb:
            victim = self._lru_loaded_excluding(incoming.name)
            if victim is None:
                # Nothing to evict but still over budget — allow the load anyway;
                # the loader itself will OOM if it truly can't fit, and that
                # error surfaces properly to the caller.
                return
            log.info("ModelPool: evicting %s to fit %s", victim.name, incoming.name)
            await victim.unload()
            self._last_used.pop(victim.name, None)

    def _lru_loaded_excluding(self, exclude: str) -> Optional[ModelLoader]:
        candidates = [(ts, n) for n, ts in self._last_used.items()
                      if n != exclude and self._loaders[n].loaded]
        if not candidates:
            return None
        candidates.sort()  # oldest first
        return self._loaders[candidates[0][1]]

    async def infer(self, task: str, image_png: Optional[bytes] = None,
                    prompt: Optional[str] = None, *,
                    max_new_tokens: Optional[int] = None,
                    wanted: Optional[Callable[[], Awaitable[bool]]] = None) -> str:
        loader = await self.ensure_loaded(task)
        # One generation at a time. The module said so, but inference ran
        # outside every lock: two in flight from PageAgent, plus a timed-out
        # client's retry, ran model.generate side by side on one T4 — seven
        # minutes of "Programming the Z80" without a single answer, no error.
        async with self._infer_lock:
            if wanted is not None and not await wanted():
                # Its client timed out while it waited. Nobody will read the
                # answer, and generating it would hold up everyone behind.
                raise Abandoned(task)
            extra: Dict[str, Any] = {"max_new_tokens": max_new_tokens} if max_new_tokens else {}
            result = await loader.infer(image_png, task, prompt=prompt, **extra)
        self._last_used[loader.name] = time.time()
        return result

    async def unload_all(self) -> None:
        async with self._lock:
            for ldr in list(self._loaders.values()):
                if ldr.loaded:
                    await ldr.unload()
            self._last_used.clear()
