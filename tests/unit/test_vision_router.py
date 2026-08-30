"""Tests for AgentRouter and vision routing."""
import json
from unittest.mock import patch, MagicMock

import pytest

from src.agents.manager.router import (
    AgentRouter,
    VISION_MODELS,
    _probe_models,
    has_vision_model,
    find_vision_host,
    formula_vision_fallback,
    vision_generate,
)


class TestProbeModels:
    def test_returns_empty_on_error(self):
        with patch("src.agents.manager.router.urllib.request.urlopen", side_effect=Exception):
            assert _probe_models("http://bad:1234") == []


class TestHasVisionModel:
    def test_true_when_llava(self):
        fake_resp = MagicMock()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)
        fake_resp.read.return_value = json.dumps({
            "models": [{"name": "llava:7b"}, {"name": "qwen2.5:7b"}]
        }).encode()
        with patch("src.agents.manager.router.urllib.request.urlopen", return_value=fake_resp):
            assert has_vision_model("http://host:11434")

    def test_false_when_no_vision(self):
        fake_resp = MagicMock()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)
        fake_resp.read.return_value = json.dumps({
            "models": [{"name": "qwen2.5:7b"}]
        }).encode()
        with patch("src.agents.manager.router.urllib.request.urlopen", return_value=fake_resp):
            assert not has_vision_model("http://host:11434")


class TestAgentRouter:
    def test_discover_vision(self):
        fake_resp = MagicMock()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)
        fake_resp.read.return_value = json.dumps({
            "models": [{"name": "llava:7b"}]
        }).encode()
        with patch("src.agents.manager.router.urllib.request.urlopen", return_value=fake_resp):
            router = AgentRouter(hosts=["http://test:11434"])
            assert router.discover_vision()
            assert router.vision_available

    def test_route_vision(self):
        router = AgentRouter(hosts=["http://test:11434"])
        router._vision_host = "http://test:11434"
        router._vision_model = "llava:7b"
        result = router.route("vision")
        assert result is not None
        assert result["host"] == "http://test:11434"
        assert result["model"] == "llava:7b"

    def test_route_text(self):
        router = AgentRouter(hosts=["http://test:11434"])
        result = router.route("text")
        assert result is not None
        assert result["host"] == "http://test:11434"

    def test_route_vision_unavailable(self):
        router = AgentRouter(hosts=["http://test:11434"])
        assert router.route("vision") is None

    def test_route_unknown_role(self):
        router = AgentRouter(hosts=["http://test:11434"])
        assert router.route("unknown") is None


class TestVisionGenerate:
    def test_returns_none_on_error(self):
        with patch("src.agents.manager.router.urllib.request.urlopen", side_effect=Exception):
            result = vision_generate("http://bad:1234", "llava:7b", "test", "base64img")
            assert result is None

    def test_returns_response(self):
        fake_resp = MagicMock()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)
        fake_resp.read.return_value = json.dumps({"response": "x^2 + 1"}).encode()
        with patch("src.agents.manager.router.urllib.request.urlopen", return_value=fake_resp):
            result = vision_generate("http://h:11434", "llava:7b", "extract", "img64")
            assert result == "x^2 + 1"
