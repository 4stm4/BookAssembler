"""Priority scheduling of Runner slots (RFC 0022 §5.6, §9 inv.9).

The point of these cases is the two pathologies strict priority creates once
bulk work is allowed onto the GPU: starvation of bulk, and inversion when
every slot is already held by bulk. A scheduler that only sorts by class
passes none of them.
"""

import asyncio

import pytest

from src.agents.manager.scheduler import Scheduler
from src.agents.tasks import Priority


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _settle():
    """Let queued waiters run to the point where they block."""
    for _ in range(4):
        await asyncio.sleep(0)


class TestOrdering:
    @pytest.mark.asyncio
    async def test_more_urgent_class_is_served_first(self):
        s = Scheduler(concurrency=1)
        await s.acquire(Priority.STRUCTURAL)          # occupies the only slot

        order = []

        async def waiter(p, tag):
            await s.acquire(p)
            order.append(tag)

        bulk = asyncio.create_task(waiter(Priority.BULK, "bulk"))
        block = asyncio.create_task(waiter(Priority.BLOCKING, "blocking"))
        await _settle()

        await s.release(Priority.STRUCTURAL)
        await _settle()
        assert order == ["blocking"], "bulk was served before blocking"

        await s.release(Priority.BLOCKING)
        await _settle()
        assert order == ["blocking", "bulk"]
        for t in (bulk, block):
            await t

    @pytest.mark.asyncio
    async def test_same_class_is_fifo_so_a_run_is_reproducible(self):
        s = Scheduler(concurrency=1)
        await s.acquire(Priority.BULK)
        order = []

        async def waiter(tag):
            await s.acquire(Priority.BULK)
            order.append(tag)

        tasks = [asyncio.create_task(waiter(i)) for i in range(3)]
        await _settle()
        for _ in range(3):
            await s.release(Priority.BULK)
            await _settle()
        assert order == [0, 1, 2]
        for t in tasks:
            await t


class TestStarvation:
    @pytest.mark.asyncio
    async def test_waiting_bulk_is_promoted_after_the_ageing_window(self):
        clock = FakeClock()
        s = Scheduler(concurrency=1, aging_seconds=300, clock=clock)
        await s.acquire(Priority.BLOCKING)

        served = []

        async def waiter(p, tag):
            await s.acquire(p)
            served.append(tag)

        old_bulk = asyncio.create_task(waiter(Priority.BULK, "old-bulk"))
        await _settle()
        clock.advance(301)                     # the bulk item has aged
        fresh = asyncio.create_task(waiter(Priority.STRUCTURAL, "fresh"))
        await _settle()

        await s.release(Priority.BLOCKING)
        await _settle()
        assert served == ["old-bulk"], (
            "an aged bulk request stayed behind a newly arrived structural one"
        )
        await s.release(Priority.BULK)
        await _settle()
        for t in (old_bulk, fresh):
            await t

    def test_bulk_never_ages_into_interactive(self):
        """§4.5: interactive means a person is waiting, and a queue cannot
        make that true after the fact."""
        clock = FakeClock()
        s = Scheduler(concurrency=1, aging_seconds=10, clock=clock)
        clock.advance(10_000)
        from src.agents.manager.scheduler import _Waiter
        aged = _Waiter(priority=int(Priority.BULK), seq=0, queued_at=0.0,
                       event=asyncio.Event())
        assert s._effective(aged, clock.now) == int(Priority.STRUCTURAL)

    def test_structural_ages_only_to_blocking(self):
        clock = FakeClock()
        s = Scheduler(concurrency=1, aging_seconds=10, clock=clock)
        from src.agents.manager.scheduler import _Waiter
        aged = _Waiter(priority=int(Priority.STRUCTURAL), seq=0,
                       queued_at=0.0, event=asyncio.Event())
        clock.advance(10_000)
        assert s._effective(aged, clock.now) == int(Priority.BLOCKING)


class TestOccupancyReserve:
    @pytest.mark.asyncio
    async def test_bulk_leaves_one_slot_for_more_urgent_work(self):
        s = Scheduler(concurrency=2)
        await s.acquire(Priority.BULK)

        second = asyncio.create_task(s.acquire(Priority.BULK))
        await _settle()
        assert s.in_flight == 1, "bulk took the last slot"

        # the reserved slot is available to a more urgent class immediately
        await asyncio.wait_for(s.acquire(Priority.BLOCKING), timeout=0.5)
        assert s.in_flight == 2

        # Only concurrency-1 = 1 bulk slot exists, so the second bulk waits
        # until the first one finishes — not until the reserved slot frees.
        await s.release(Priority.BLOCKING)
        await _settle()
        assert not second.done(), "bulk got the reserved slot"

        await s.release(Priority.BULK)
        await _settle()
        assert second.done()
        await second
        await s.release(Priority.BULK)

    @pytest.mark.asyncio
    async def test_a_single_slot_has_nothing_to_reserve(self):
        """With concurrency=1 ageing is the only guard — stated in §5.6."""
        s = Scheduler(concurrency=1)
        await asyncio.wait_for(s.acquire(Priority.BULK), timeout=0.5)
        assert s.in_flight == 1


class TestCancellation:
    @pytest.mark.asyncio
    async def test_a_hung_up_client_frees_the_queue(self):
        """§5.6 rule 4: a page the user already closed must not hold a slot."""
        s = Scheduler(concurrency=1)
        await s.acquire(Priority.BLOCKING)

        abandoned = asyncio.create_task(s.acquire(Priority.STRUCTURAL))
        await _settle()
        assert s.depth_by_priority()[int(Priority.STRUCTURAL)] == 1

        abandoned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandoned
        assert s.depth_by_priority() == {}


def test_concurrency_must_be_positive():
    with pytest.raises(ValueError):
        Scheduler(concurrency=0)
