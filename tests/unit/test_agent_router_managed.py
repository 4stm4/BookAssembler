"""Unit tests for Stage 6 of RFC 0022 — router support for kind='managed'.

- probe_managed returns the health body verbatim so KAE agent-manager can
  surface runner state / runner_url / queue_depth to the UI.
- pick() routes to a managed agent only when its Runner is UP; otherwise it
  looks for another agent with the role. Vision roles never fall back to
  ollama, so if no managed/vision agent is up we return no host.
"""

import json
from unittest.mock import patch

import pytest

from src.agents import router


def test_probe_managed_returns_full_health_body():
    fake = {"status": "ok", "kind": "managed",
            "tasks": ["table", "vision"],
            "runner": "up", "runner_url": "https://r.example",
            "queue_depth": 0}

    class Resp:
        def __init__(self, body): self._body = body
        def read(self): return self._body.encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    with patch.object(router.urllib.request, "urlopen",
                      lambda *a, **k: Resp(json.dumps(fake))):
        ok, body = router.probe_managed("https://mgr.example")
    assert ok is True
    assert body["runner"] == "up"
    assert body["tasks"] == ["table", "vision"]


def test_probe_managed_marks_unreachable_on_network_error():
    def boom(*a, **k):
        raise RuntimeError("net")
    with patch.object(router.urllib.request, "urlopen", boom):
        ok, body = router.probe_managed("https://down")
    assert ok is False
    assert body == {}


def _make_agents(tmp_path, entries):
    p = tmp_path / "agents.json"
    p.write_text(json.dumps(entries))
    return str(p)


def test_pick_routes_to_managed_when_runner_up(monkeypatch, tmp_path):
    entries = [{"name": "M", "host": "https://mgr",
                "kind": "managed", "roles": ["table"],
                "active_model": ""}]
    monkeypatch.setattr(router, "AGENTS_CONFIG_PATH",
                        _make_agents(tmp_path, entries))
    monkeypatch.setattr(router, "_LEGACY_PATH", "/nowhere")
    monkeypatch.setattr(router, "probe_managed",
                        lambda h: (True, {"runner": "up", "tasks": ["table"]}))
    host, model, kind = router.pick("table")
    assert (host, kind) == ("https://mgr", "managed")
    assert model == "table"


def test_pick_skips_managed_when_runner_cold(monkeypatch, tmp_path):
    entries = [
        {"name": "M", "host": "https://mgr", "kind": "managed",
         "roles": ["table"], "active_model": ""},
        {"name": "OCR", "host": "https://ocr", "kind": "multimodel",
         "roles": ["table"], "active_model": ""},
    ]
    monkeypatch.setattr(router, "AGENTS_CONFIG_PATH",
                        _make_agents(tmp_path, entries))
    monkeypatch.setattr(router, "_LEGACY_PATH", "/nowhere")
    monkeypatch.setattr(router, "probe_managed",
                        lambda h: (True, {"runner": "cold", "tasks": ["table"]}))
    monkeypatch.setattr(router, "_probe_health",
                        lambda h: (True, ["table"]))
    host, _model, kind = router.pick("table")
    # Managed was skipped (Runner cold), fell through to multimodel.
    assert (host, kind) == ("https://ocr", "multimodel")


def test_pick_returns_none_for_vision_when_no_agent_ready(monkeypatch, tmp_path):
    entries = [{"name": "M", "host": "https://mgr", "kind": "managed",
                "roles": ["vision"], "active_model": ""}]
    monkeypatch.setattr(router, "AGENTS_CONFIG_PATH",
                        _make_agents(tmp_path, entries))
    monkeypatch.setattr(router, "_LEGACY_PATH", "/nowhere")
    monkeypatch.setattr(router, "probe_managed",
                        lambda h: (True, {"runner": "warming"}))
    host, model, kind = router.pick("vision")
    assert (host, model, kind) == (None, None, "")
