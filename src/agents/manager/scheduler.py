"""Priority scheduling of the Runner's slots (RFC 0022 §5.6).

Strict priority alone produces two well-known pathologies, and both are real
here once bulk work is allowed onto the GPU:

  * **starvation** — a book translation is thousands of requests, so a strict
    queue may not serve `bulk` once in an hour;
  * **inversion through occupancy** — if every in-flight slot holds `bulk`, an
    arriving `interactive` waits on somebody else's work rather than on the
    queue.

So: ageing bounds the first, a reserved slot bounds the second. The reserve
only exists when there is more than one slot; with a single slot a long bulk
inference holds it to the end either way, because preempting would mean
aborting generation on a Runner that keeps no state (§2.2).

The scheduler lives here and only here. The Runner executes one request at a
time and knows nothing about classes — splitting the decision across two
processes would put scheduling state in the one that is designed to die.
"""

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from src.agents.tasks import Priority


@dataclass(order=True)
class _Waiter:
    priority: int
    seq: int
    queued_at: float = field(compare=False)
    event: asyncio.Event = field(compare=False)
    cancelled: bool = field(default=False, compare=False)


class Scheduler:
    """Hands out in-flight slots by priority class.

    `aging_seconds` promotes a waiting request one class at a time; the floor
    keeps `bulk` from ever reaching `interactive`, which is granted only to a
    request arriving from a user action (§4.5).
    """

    def __init__(self, concurrency: int = 2, aging_seconds: float = 300.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self.concurrency = concurrency
        self.aging_seconds = aging_seconds
        self._clock = clock
        self._waiting: List[_Waiter] = []
        self._in_flight: Dict[int, int] = {}
        self._seq = itertools.count()
        self._lock = asyncio.Lock()

    # -- introspection used by /metrics -------------------------------------

    @property
    def in_flight(self) -> int:
        return sum(self._in_flight.values())

    def depth_by_priority(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for w in self._waiting:
            if not w.cancelled:
                out[w.priority] = out.get(w.priority, 0) + 1
        return out

    # -- policy -------------------------------------------------------------

    @staticmethod
    def _floor(priority: int) -> int:
        """How far ageing may promote this class.

        Nothing is ever promoted into `interactive`: that class means a person
        is waiting right now, and a queue cannot make that true after the fact.
        """
        if priority >= Priority.BULK:
            return int(Priority.STRUCTURAL)
        return int(Priority.BLOCKING)

    def _effective(self, w: _Waiter, now: float) -> int:
        if self.aging_seconds <= 0:
            return w.priority
        steps = int((now - w.queued_at) // self.aging_seconds)
        return max(self._floor(w.priority), w.priority - steps)

    def _bulk_would_take_the_last_slot(self, priority: int) -> bool:
        if priority < Priority.BULK or self.concurrency < 2:
            return False
        return self.in_flight + 1 >= self.concurrency

    def _pick(self, now: float) -> Optional[_Waiter]:
        """The next request to admit, or None if nothing may start."""
        if self.in_flight >= self.concurrency:
            return None
        best: Optional[_Waiter] = None
        best_key = None
        for w in self._waiting:
            if w.cancelled:
                continue
            if self._bulk_would_take_the_last_slot(w.priority):
                continue
            # Ageing first, then arrival order: two requests of the same
            # effective class are served in the order they were queued, which
            # is what makes a run reproducible.
            key = (self._effective(w, now), w.seq)
            if best_key is None or key < best_key:
                best, best_key = w, key
        return best

    async def _promote(self) -> None:
        now = self._clock()
        while True:
            w = self._pick(now)
            if w is None:
                return
            self._waiting.remove(w)
            self._in_flight[w.priority] = self._in_flight.get(w.priority, 0) + 1
            w.event.set()

    # -- public API ---------------------------------------------------------

    async def acquire(self, priority: int) -> None:
        """Wait until this request may run."""
        w = _Waiter(priority=int(priority), seq=next(self._seq),
                    queued_at=self._clock(), event=asyncio.Event())
        async with self._lock:
            self._waiting.append(w)
            await self._promote()
        try:
            await w.event.wait()
        except asyncio.CancelledError:
            # The client hung up. Drop it rather than hold a slot for a page
            # nobody is looking at any more (§5.6 rule 4).
            async with self._lock:
                w.cancelled = True
                if w in self._waiting:
                    self._waiting.remove(w)
                else:
                    self._release_locked(w.priority)
                await self._promote()
            raise

    def _release_locked(self, priority: int) -> None:
        n = self._in_flight.get(priority, 0)
        if n <= 1:
            self._in_flight.pop(priority, None)
        else:
            self._in_flight[priority] = n - 1

    async def release(self, priority: int) -> None:
        async with self._lock:
            self._release_locked(int(priority))
            await self._promote()

    def waited_seconds(self, queued_at: float) -> float:
        return self._clock() - queued_at
