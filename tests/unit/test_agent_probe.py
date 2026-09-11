"""Probing a GPU agent behind a tunnel (RFC 0022 §4.1).

One slow answer to one 5 s probe counted as "no agent", and OCR skipped its
whole step in silence: 5 pages of "Programming the Z80" left without text,
the runner answering /health in 0.4 s a minute later.
"""
import json
import socket
import urllib.error

from src.agents import router


class _Resp:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_slow_first_answer_gets_a_second_longer_look(monkeypatch):
    timeouts = []

    def urlopen(req, timeout=None):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            raise socket.timeout("The read operation timed out")
        return _Resp({"status": "ok", "tasks": ["vision", "translate"]})

    monkeypatch.setattr(router.urllib.request, "urlopen", urlopen)
    assert router._probe_health("http://gpu") == (True, ["vision", "translate"])
    assert timeouts == [5, 15]


def test_a_dead_tunnel_is_not_waited_for(monkeypatch):
    """DNS fails at once: no second look, no wait."""
    calls = []

    def urlopen(req, timeout=None):
        calls.append(timeout)
        raise urllib.error.URLError("[Errno -2] Name or service not known")

    monkeypatch.setattr(router.urllib.request, "urlopen", urlopen)
    assert router._probe_health("http://gone") == (False, [])
    assert calls == [5]


def test_an_agent_that_never_answers_is_reported(monkeypatch, caplog):
    def urlopen(req, timeout=None):
        raise socket.timeout("The read operation timed out")

    monkeypatch.setattr(router.urllib.request, "urlopen", urlopen)
    ok, _ = router.probe_managed("http://gpu")
    assert not ok
    assert "http://gpu not reachable" in caplog.text
