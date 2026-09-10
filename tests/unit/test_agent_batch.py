"""Bounded fan-out with a failure budget that actually holds.

Submitting every task upfront made the budget unenforceable: Future.cancel()
only reaches tasks that have not started, so an agent that fails instantly was
asked about the whole book before the first cancellation landed.
"""
import threading

import pytest

from src.analyzers._agent_batch import run_bounded


class TestBudget:
    def test_instant_failures_still_stop_early(self):
        """The case that defeated cancel(): failures with no delay at all."""
        calls = []

        def work(x):
            calls.append(x)
            raise RuntimeError("agent down")

        results, failures = run_bounded(list(range(100)), work,
                                        concurrency=2, budget=5)
        assert results == {}
        assert len(calls) < 100, "asked a dead agent about every item"
        assert len(calls) <= 5 + 2 + 2, f"overshot the budget: {len(calls)}"

    def test_one_bad_item_does_not_stop_the_rest(self):
        def work(x):
            if x == 3:
                raise RuntimeError("bad page")
            return x * 10

        results, failures = run_bounded(list(range(10)), work,
                                        concurrency=3, budget=5)
        assert failures == 1
        assert len(results) == 9
        assert results[0] == 0 and results[9] == 90

    def test_results_are_keyed_by_input_position(self):
        """Completion order must not decide which answer belongs to which item."""
        def work(x):
            return f"r{x}"

        results, _ = run_bounded(["a", "b", "c"], lambda x: work(x),
                                 concurrency=3, budget=1)
        assert results == {0: "ra", 1: "rb", 2: "rc"}


class TestConcurrency:
    def test_never_exceeds_the_limit(self):
        peak = 0
        cur = 0
        lock = threading.Lock()

        def work(x):
            nonlocal peak, cur
            with lock:
                cur += 1
                peak = max(peak, cur)
            try:
                threading.Event().wait(0.02)
                return x
            finally:
                with lock:
                    cur -= 1

        run_bounded(list(range(12)), work, concurrency=3, budget=99)
        assert peak <= 3, f"ran {peak} at once with a limit of 3"

    def test_actually_overlaps(self):
        peak = 0
        cur = 0
        lock = threading.Lock()

        def work(x):
            nonlocal peak, cur
            with lock:
                cur += 1
                peak = max(peak, cur)
            try:
                threading.Event().wait(0.05)
                return x
            finally:
                with lock:
                    cur -= 1

        run_bounded(list(range(6)), work, concurrency=3, budget=99)
        assert peak > 1, "ran one at a time despite a limit above one"

    def test_empty_input_is_fine(self):
        assert run_bounded([], lambda x: x, concurrency=2, budget=1) == ({}, 0)
