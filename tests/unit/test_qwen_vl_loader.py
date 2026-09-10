"""
QwenVLLoader contract tests (RFC 0022 §6).

These tests do NOT touch a real GPU or download the model — they verify:
  * the loader satisfies the ModelLoader protocol shape,
  * construction is cheap (no torch/transformers import),
  * `load()` raises a clear error when CUDA is unavailable,
  * `infer()` before `load()` raises a clear error.
"""

from src.agents.tasks import ALL_TASKS
import asyncio

import pytest

from src.agents.runner.loaders import QwenVLLoader
from src.agents.runner.loaders.base import ModelLoader


def test_construction_is_cheap() -> None:
    ldr = QwenVLLoader()
    assert ldr.name == "Qwen2.5-VL-7B-Instruct"
    # RFC 0022 §9 inv.11 — one model serves every task in the registry;
    # a second one would not fit beside it on a 16 GB card.
    assert set(ldr.tasks) == set(ALL_TASKS)
    assert ldr.vram_mb > 0
    assert ldr.loaded is False


def test_protocol_shape() -> None:
    ldr: ModelLoader = QwenVLLoader()  # runtime protocol check via annotation
    for attr in ("name", "tasks", "vram_mb", "loaded", "load", "unload", "infer"):
        assert hasattr(ldr, attr), f"missing {attr}"


def test_infer_before_load_raises() -> None:
    ldr = QwenVLLoader()
    with pytest.raises(RuntimeError, match="before load"):
        asyncio.run(ldr.infer(b"\x89PNG...", "table"))


def test_load_without_cuda_reports_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate CPU-only host: torch present but no CUDA."""
    try:
        import torch  # noqa: F401
    except Exception:
        pytest.skip("torch not installed in test env")

    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    ldr = QwenVLLoader()
    with pytest.raises(RuntimeError, match="requires CUDA"):
        asyncio.run(ldr.load())
    assert ldr.loaded is False


def test_unload_before_load_is_noop() -> None:
    ldr = QwenVLLoader()
    asyncio.run(ldr.unload())
    assert ldr.loaded is False
