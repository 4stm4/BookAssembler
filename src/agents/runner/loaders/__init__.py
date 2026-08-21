"""
Model loaders — each task maps to a loader that knows how to (un)load a model
and run inference on a PNG bytes payload.

Real loaders (Qwen2.5-VL, GOT-OCR, MinerU) implement ModelLoader in dedicated
modules. `EchoLoader` is used by tests and dev-mode notebooks — no GPU needed.
"""

from typing import Callable, Dict, List

from src.agents.runner.loaders.base import EchoLoader, ModelLoader
from src.agents.runner.loaders.qwen_vl import QwenVLLoader


# Slug → factory. Slugs come from KAE_RUNNER_LOADERS and stay stable so the
# Kaggle notebook can flip between models without shipping code.
LOADER_REGISTRY: Dict[str, Callable[[], ModelLoader]] = {
    "echo": lambda: EchoLoader(),
    "qwen_vl": lambda: QwenVLLoader(),
}


def build_loaders(slugs: List[str]) -> List[ModelLoader]:
    """Resolve config slugs to loader instances. Empty list → caller
    decides the default (usually EchoLoader).
    """
    resolved: List[ModelLoader] = []
    for slug in slugs:
        factory = LOADER_REGISTRY.get(slug)
        if factory is None:
            raise KeyError(
                f"Unknown loader slug {slug!r}. "
                f"Known: {sorted(LOADER_REGISTRY)}"
            )
        resolved.append(factory())
    return resolved


__all__ = [
    "ModelLoader", "EchoLoader", "QwenVLLoader",
    "LOADER_REGISTRY", "build_loaders",
]
