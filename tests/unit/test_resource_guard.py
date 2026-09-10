"""src/jobs/resource_guard.py — RFC 0019 §3 memory guardrail."""

import asyncio

import pytest

from src.jobs import resource_guard
from src.jobs.resource_guard import ResourceGuard


@pytest.fixture
def ram(monkeypatch):
    """Set the reported RAM percent (None = unmeasurable)."""
    def _set(value):
        monkeypatch.setattr(resource_guard, "_ram_percent", lambda: value)
    return _set


def test_available_when_below_threshold(ram):
    ram(50.0)
    assert ResourceGuard.check_memory_available() is True


def test_unavailable_when_over_threshold(ram):
    ram(92.0)
    assert ResourceGuard.check_memory_available() is False


def test_noop_when_unmeasurable(ram):
    ram(None)
    assert ResourceGuard.check_memory_available() is True


def test_wait_returns_immediately_when_available(ram):
    ram(10.0)
    assert asyncio.run(ResourceGuard.wait_for_memory(timeout=5.0)) is True


def test_wait_times_out_and_proceeds(ram):
    ram(99.0)
    assert asyncio.run(
        ResourceGuard.wait_for_memory(timeout=0.3, poll=0.1)
    ) is False


def test_wait_unblocks_when_memory_frees(monkeypatch):
    seq = iter([95.0, 95.0, 40.0])
    monkeypatch.setattr(resource_guard, "_ram_percent", lambda: next(seq, 40.0))
    assert asyncio.run(
        ResourceGuard.wait_for_memory(timeout=5.0, poll=0.05)
    ) is True
