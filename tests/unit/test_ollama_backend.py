"""Unit tests for OllamaBackend (src/agents/manager/backends/ollama.py)."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.agents.manager.backends.ollama import OllamaBackend


def run(coro):
    return asyncio.run(coro)


class TestOllamaBackendInit:
    def test_default_host(self):
        b = OllamaBackend()
        assert b.host == "http://localhost:11434"

    def test_custom_host(self):
        b = OllamaBackend(host="http://orangepi:11434/")
        assert b.host == "http://orangepi:11434"

    def test_host_from_env(self, monkeypatch):
        monkeypatch.setenv("KAE_OLLAMA_HOST", "http://192.168.88.74:11434")
        b = OllamaBackend()
        assert b.host == "http://192.168.88.74:11434"

    def test_explicit_host_overrides_env(self, monkeypatch):
        monkeypatch.setenv("KAE_OLLAMA_HOST", "http://env-host:11434")
        b = OllamaBackend(host="http://explicit:11434")
        assert b.host == "http://explicit:11434"


class TestOllamaBackendStartStop:
    def test_start_returns_host(self):
        b = OllamaBackend(host="http://orangepi:11434")
        result = run(b.start())
        assert result == "http://orangepi:11434"

    def test_stop_is_noop(self):
        b = OllamaBackend()
        run(b.stop())


class TestOllamaBackendStatus:
    def test_status_up_urllib(self):
        b = OllamaBackend(host="http://fake:11434")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with patch.dict("sys.modules", {"httpx": None}):
                result = run(b._status_urllib())
        assert result == "up"

    def test_status_cold_on_connection_error(self):
        b = OllamaBackend(host="http://fake:11434")
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = run(b._status_urllib())
        assert result == "cold"

    def test_status_error_on_bad_status(self):
        b = OllamaBackend(host="http://fake:11434")
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = run(b._status_urllib())
        assert result == "error"
