"""
Model loaders — each task maps to a loader that knows how to (un)load a model
and run inference on a PNG bytes payload.

Real loaders (Qwen2.5-VL, GOT-OCR, MinerU) implement ModelLoader in dedicated
modules. `EchoLoader` is used by tests and dev-mode notebooks — no GPU needed.
"""

from src.agents.runner.loaders.base import EchoLoader, ModelLoader

__all__ = ["ModelLoader", "EchoLoader"]
