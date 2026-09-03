"""GPU-first text generation with an edge-cluster fallback (RFC 0022 §4.4, §7.2).

These are the two stages the v1.2.0 change exists for: until it, `refine` and
`translate` could not reach the GPU at all, because /infer required an image.
"""

import pytest

from src.agents import text as agent_text
from src.agents.tasks import Priority


class TestRouting:
    def test_gpu_is_tried_first(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(agent_text, "pick",
                            lambda role: ("http://gpu", "m", "managed"))
        monkeypatch.setattr(agent_text, "call_infer",
                            lambda host, task, **kw: seen.update(
                                host=host, task=task, **kw) or "с GPU")
        monkeypatch.setattr(agent_text, "_edge_generate",
                            lambda *a, **k: pytest.fail("edge was used"))

        assert agent_text.generate_text("текст", task="translate") == "с GPU"
        assert seen["host"] == "http://gpu"
        assert seen["task"] == "translate"
        assert seen["prompt"] == "текст"

    def test_bulk_priority_is_declared(self, monkeypatch):
        """Translation must not outrank a page the user is looking at."""
        seen = {}
        monkeypatch.setattr(agent_text, "pick",
                            lambda role: ("http://gpu", "m", "managed"))
        monkeypatch.setattr(agent_text, "call_infer",
                            lambda host, task, **kw: seen.update(kw) or "x")
        agent_text.generate_text("t", task="translate")
        assert seen["priority"] == int(Priority.BULK)

    def test_a_refusal_falls_back_to_the_edge(self, monkeypatch):
        """429 over the bulk budget, a dead tunnel and a timeout all mean the
        same thing here: this work has to happen somewhere else."""
        monkeypatch.setattr(agent_text, "pick",
                            lambda role: ("http://gpu", "m", "managed"))
        monkeypatch.setattr(agent_text, "call_infer", lambda *a, **k: None)
        monkeypatch.setattr(agent_text, "_edge_generate",
                            lambda prompt, host=None, model=None: "с edge")
        assert agent_text.generate_text("t", task="refine") == "с edge"

    def test_no_agent_at_all_goes_straight_to_the_edge(self, monkeypatch):
        monkeypatch.setattr(agent_text, "pick", lambda role: (None, None, ""))
        monkeypatch.setattr(agent_text, "_edge_generate",
                            lambda prompt, host=None, model=None: "с edge")
        assert agent_text.generate_text("t") == "с edge"

    def test_an_explicit_host_takes_no_gpu_slot(self, monkeypatch):
        """The caller already said where it wants to go."""
        monkeypatch.setattr(agent_text, "pick",
                            lambda role: pytest.fail("discovery ran anyway"))
        monkeypatch.setattr(agent_text, "_edge_generate",
                            lambda prompt, host=None, model=None: f"на {host}")
        assert agent_text.generate_text("t", host="http://edge") == "на http://edge"


class TestDeterminism:
    def test_edge_call_pins_temperature_and_seed(self, monkeypatch):
        """RFC 0012 §3.1 — the fallback must not be less deterministic."""
        import json
        seen = {}

        class _Resp:
            def read(self): return json.dumps({"response": "ok"}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(agent_text.urllib.request, "urlopen",
                            lambda req, timeout=None:
                            seen.update(json.loads(req.data.decode())) or _Resp())
        agent_text._edge_generate("prompt")
        assert seen["options"]["temperature"] == 0.0
        assert seen["options"]["seed"] == 42
