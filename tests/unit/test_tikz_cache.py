"""Content-addressed cache for diagram vectorization (RFC 0021 §3.1)."""

import numpy as np

from src.assembler import diagram_vectorizer as dv


def _image(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(8, 8, 3), dtype=np.uint8)


def test_same_region_and_backend_share_a_key() -> None:
    labels = [{"text": "CPU", "x": 1}]

    assert dv._cache_key(_image(), labels, "cv_fallback") == dv._cache_key(
        _image(), labels, "cv_fallback"
    )


def test_key_changes_with_pixels_labels_or_backend() -> None:
    labels = [{"text": "CPU", "x": 1}]
    base = dv._cache_key(_image(1), labels, "cv_fallback")

    assert dv._cache_key(_image(2), labels, "cv_fallback") != base
    assert dv._cache_key(_image(1), [{"text": "MEM"}], "cv_fallback") != base
    assert dv._cache_key(_image(1), labels, "cloud_vision") != base


def test_round_trip_through_the_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KAE_SSD_PATH", str(tmp_path))

    assert dv._cache_read("deadbeef") is None

    dv._cache_write("deadbeef", "\\begin{tikzpicture}\\end{tikzpicture}")

    assert dv._cache_read("deadbeef") == "\\begin{tikzpicture}\\end{tikzpicture}"


def test_backend_id_follows_the_environment(monkeypatch) -> None:
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VISION_OLLAMA_MODEL", "LLM_TIKZ_MODEL"):
        monkeypatch.delenv(var, raising=False)
    assert dv._backend_id() == "cv_fallback"

    monkeypatch.setenv("VISION_OLLAMA_MODEL", "llava:13b")
    assert dv._backend_id() == "ollama_vision:llava:13b"

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert dv._backend_id() == "cloud_vision"


def test_unwritable_cache_dir_does_not_raise(tmp_path, monkeypatch) -> None:
    """A read-only cache location degrades to no caching, it does not fail a build."""
    monkeypatch.setenv("KAE_SSD_PATH", str(tmp_path / "nested"))
    (tmp_path).chmod(0o500)
    try:
        dv._cache_write("key", "tikz")
    finally:
        (tmp_path).chmod(0o700)
