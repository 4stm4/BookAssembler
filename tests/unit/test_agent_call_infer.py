"""call_infer endpoint selection and retry policy (src/agents/router.py)."""
import io
import json
import socket
import urllib.error
from typing import List

import pytest

from src.agents import router


class _Resp(io.BytesIO):
    """Minimal stand-in for the urlopen context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(router.time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def _no_token(monkeypatch):
    monkeypatch.setattr(router, "load_agents", lambda: [])


def _install(monkeypatch, handler):
    """Record every requested URL and delegate the response to `handler`."""
    calls: List[str] = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return handler(req.full_url)

    monkeypatch.setattr(router.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_infer_success_does_not_call_ocr(monkeypatch):
    calls = _install(
        monkeypatch, lambda url: _Resp(json.dumps({"text": "ok"}).encode())
    )
    assert router.call_infer("http://h", "vision", b"img") == "ok"
    assert calls == ["http://h/infer"]


def test_non_timeout_failure_falls_back_to_ocr(monkeypatch):
    """A got-ocr agent 404s on /infer — /ocr must still be tried."""

    def handler(url):
        if url.endswith("/infer"):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return _Resp(json.dumps({"text": "from-ocr"}).encode())

    calls = _install(monkeypatch, handler)
    assert router.call_infer("http://h", "vision", b"img") == "from-ocr"
    assert calls == ["http://h/infer", "http://h/ocr"]


def test_timeout_retries_then_skips_ocr(monkeypatch):
    """A saturated uplink: retry /infer, but never queue more bytes on /ocr."""

    def handler(url):
        raise socket.timeout("The read operation timed out")

    calls = _install(monkeypatch, handler)
    assert router.call_infer("http://h", "vision", b"img") is None
    assert calls == ["http://h/infer"] * router.INFER_ATTEMPTS


def test_timeout_then_success_within_retries(monkeypatch):
    state = {"n": 0}

    def handler(url):
        state["n"] += 1
        if state["n"] < router.INFER_ATTEMPTS:
            raise socket.timeout("The read operation timed out")
        return _Resp(json.dumps({"text": "late"}).encode())

    calls = _install(monkeypatch, handler)
    assert router.call_infer("http://h", "vision", b"img") == "late"
    assert len(calls) == router.INFER_ATTEMPTS
