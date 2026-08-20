"""Unit tests for KaggleKernelBackend (RFC 0022 §5.1, Stage 3).

The `kaggle` package is not required at test time — we inject a fake API
object into the backend, so tests are hermetic and never hit the network.
"""

import asyncio
import os
import tempfile
from types import SimpleNamespace
from typing import Any, List, Tuple

import pytest

from src.agents.manager.backends.kaggle import KaggleKernelBackend


class FakeKaggleApi:
    """Minimal stand-in for kaggle.api.kaggle_api_extended.KaggleApi."""

    def __init__(self, status_value: str = "queued", push_raises: Exception = None) -> None:
        self.status_value = status_value
        self.push_raises = push_raises
        self.push_calls: List[str] = []
        self.status_calls: List[Tuple[str, str]] = []

    def kernels_push_cli(self, folder: str) -> Any:
        self.push_calls.append(folder)
        if self.push_raises:
            raise self.push_raises
        return SimpleNamespace(ref="fake/ref", versionNumber=1)

    def kernels_status(self, owner: str, slug: str) -> Any:
        self.status_calls.append((owner, slug))
        return SimpleNamespace(status=self.status_value)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_constructor_requires_owner_slash_slug():
    with pytest.raises(ValueError):
        KaggleKernelBackend(kernel="badformat", api=FakeKaggleApi())


def test_start_pushes_kernel_folder():
    api = FakeKaggleApi()
    with tempfile.TemporaryDirectory() as d:
        # Simulate a valid kernel dir on disk.
        with open(os.path.join(d, "kernel-metadata.json"), "w") as f:
            f.write("{}")
        b = KaggleKernelBackend("user/slug", kernel_dir=d, api=api)
        result = _run(b.start())
        assert result is None      # URL comes via announce (RFC 0022 §5.2)
        assert api.push_calls == [d]


def test_start_fails_fast_without_kernel_dir():
    b = KaggleKernelBackend("user/slug", kernel_dir="/nonexistent", api=FakeKaggleApi())
    with pytest.raises(RuntimeError, match="kernel_dir"):
        _run(b.start())


@pytest.mark.parametrize("kaggle_status,expected", [
    ("queued", "starting"),
    ("running", "up"),
    ("complete", "cold"),
    ("cancelled", "cold"),
    ("error", "error"),
    ("failed", "error"),
    ("unknown-junk", "error"),  # defensive default
])
def test_status_maps_kaggle_states(kaggle_status, expected):
    b = KaggleKernelBackend("u/s", api=FakeKaggleApi(status_value=kaggle_status))
    assert _run(b.status()) == expected


def test_status_returns_error_on_api_exception():
    class Boom(FakeKaggleApi):
        def kernels_status(self, owner: str, slug: str) -> Any:
            raise RuntimeError("network down")

    b = KaggleKernelBackend("u/s", api=Boom())
    assert _run(b.status()) == "error"


def test_stop_is_noop_and_does_not_call_api():
    api = FakeKaggleApi()
    b = KaggleKernelBackend("u/s", api=api)
    _run(b.stop())          # must not raise
    assert api.push_calls == []
    assert api.status_calls == []


def test_manager_app_wires_backend_from_config(monkeypatch):
    """cfg.backend='kaggle' must pick KaggleKernelBackend without touching the
    real kaggle package (we substitute the module-level import path)."""
    import src.agents.manager.app as app_mod
    from src.agents.manager.config import ManagerConfig

    class DummyBackend:
        async def start(self): return None
        async def stop(self): return None
        async def status(self): return "cold"

    monkeypatch.setattr(
        "src.agents.manager.backends.kaggle.KaggleKernelBackend",
        lambda **kw: DummyBackend(),
    )
    cfg = ManagerConfig(backend="kaggle", kaggle_kernel="u/s", kaggle_kernel_dir="/tmp")
    app = app_mod.create_app(cfg)
    assert isinstance(app.state.orchestrator.backend, DummyBackend)


def test_unknown_backend_raises_at_construction():
    from src.agents.manager.app import create_app
    from src.agents.manager.config import ManagerConfig
    cfg = ManagerConfig(backend="martian")
    with pytest.raises(ValueError, match="Unknown backend"):
        create_app(cfg)
