"""call_infer endpoint selection and retry policy (src/agents/router.py).

A role has a route of its own (RFC 0022 §4.4: /vision, /table, /formula,
/refine, /translate), tried first; /infer - the shared envelope - is the
fallback for a Runner not yet on that version, and /ocr the legacy alias
that only ever spoke image payloads."""
from src.agents.tasks import Priority
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


def _not_found(url):
    return urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def test_a_role_s_own_route_answers_and_nothing_else_is_called(monkeypatch):
    calls = _install(
        monkeypatch, lambda url: _Resp(json.dumps({"text": "ok"}).encode())
    )
    assert router.call_infer("http://h", "vision", b"img") == "ok"
    assert calls == ["http://h/vision"]


def test_a_runner_without_role_routes_answers_on_infer(monkeypatch):
    """A Runner still on the shared envelope 404s on /vision."""

    def handler(url):
        if url.endswith("/vision"):
            raise _not_found(url)
        return _Resp(json.dumps({"text": "from-infer"}).encode())

    calls = _install(monkeypatch, handler)
    assert router.call_infer("http://h", "vision", b"img") == "from-infer"
    assert calls == ["http://h/vision", "http://h/infer"]


def test_non_timeout_failure_falls_back_to_ocr(monkeypatch):
    """A got-ocr agent 404s on the role's route and on /infer — /ocr must
    still be tried."""

    def handler(url):
        if not url.endswith("/ocr"):
            raise _not_found(url)
        return _Resp(json.dumps({"text": "from-ocr"}).encode())

    calls = _install(monkeypatch, handler)
    assert router.call_infer("http://h", "vision", b"img") == "from-ocr"
    assert calls == ["http://h/vision", "http://h/infer", "http://h/ocr"]


def test_a_task_with_no_route_of_its_own_goes_to_infer(monkeypatch):
    calls = _install(
        monkeypatch, lambda url: _Resp(json.dumps({"text": "ok"}).encode())
    )
    assert router.call_infer("http://h", "ocr", b"img") == "ok"
    assert calls == ["http://h/infer"]


def test_timeout_retries_then_tries_no_other_route(monkeypatch):
    """A saturated uplink: retry the route, but never queue more bytes on
    /infer or /ocr behind it."""

    def handler(url):
        raise socket.timeout("The read operation timed out")

    calls = _install(monkeypatch, handler)
    assert router.call_infer("http://h", "vision", b"img") is None
    assert calls == ["http://h/vision"] * router.INFER_ATTEMPTS


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


# --- text tasks and priority (RFC 0022 v1.2.0 §4.4, §4.5) ------------------

class TestTextTasksAndPriority:
    def _capture(self, monkeypatch):
        """Record what would go on the wire instead of sending it."""
        seen = {}

        def fake_post(url, payload, headers, timeout=None, attempts=None):
            seen["url"] = url
            seen["body"] = json.loads(payload.decode())
            return "ok", None

        monkeypatch.setattr(router, "_post_infer", fake_post)
        return seen

    def test_text_task_sends_no_image(self, monkeypatch):
        seen = self._capture(monkeypatch)
        out = router.call_infer("http://a", "translate", prompt="текст")
        assert out == "ok"
        assert "image_b64" not in seen["body"]
        assert seen["body"]["prompt"] == "текст"

    def test_priority_is_stamped_and_clamped(self, monkeypatch):
        """§9 inv.8: a caller cannot label its bulk work interactive."""
        seen = self._capture(monkeypatch)
        router.call_infer("http://a", "translate", prompt="x", priority=0)
        assert seen["body"]["priority"] == int(Priority.BULK)

    def test_ocr_defaults_to_blocking(self, monkeypatch):
        seen = self._capture(monkeypatch)
        router.call_infer("http://a", "ocr", image_png=b"png")
        assert seen["body"]["priority"] == int(Priority.BLOCKING)

    def test_a_bad_payload_never_leaves_the_process(self, monkeypatch):
        """The Runner would answer 400 anyway; a queued bad request still
        occupies a slot while it waits."""
        called = []
        monkeypatch.setattr(router, "_post_infer",
                            lambda *a, **k: called.append(1) or ("x", None))
        assert router.call_infer("http://a", "ocr") is None       # no image
        assert router.call_infer("http://a", "refine") is None    # no prompt
        assert called == []

    def test_text_task_does_not_fall_back_to_the_legacy_ocr_path(self, monkeypatch):
        """/ocr only ever spoke image payloads."""
        urls = []

        def fake_post(url, payload, headers, timeout=None, attempts=None):
            urls.append(url)
            return None, None

        monkeypatch.setattr(router, "_post_infer", fake_post)
        router.call_infer("http://a", "refine", prompt="x")
        assert urls == ["http://a/refine", "http://a/infer"]

    def test_ollama_text_task_carries_no_images_field(self, monkeypatch):
        """The edge-cluster fallback path for bulk work (RFC 0022 §7.2)."""
        seen = {}

        class _Resp:
            def read(self): return json.dumps({"response": "ответ"}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            seen["body"] = json.loads(req.data.decode())
            return _Resp()

        monkeypatch.setattr(router.urllib.request, "urlopen", fake_urlopen)
        out = router.call_infer("http://o", "translate", prompt="x",
                                kind="ollama")
        assert out == "ответ"
        assert "images" not in seen["body"]
