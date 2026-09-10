"""RunnerClient — the Manager's own HTTP client to the Runner (RFC 0022 §4.2).

This is the one hop every fixture in test_agent_manager.py replaces with a
fake, which is exactly how base64.b64encode(None) survived here through the
whole v1.2.0 change: every text-task test passed while patching over the seam
that broke on the real path to Kaggle.
"""

import json

import pytest

from src.agents.manager.runner_client import RunnerClient


class _Capture:
    """Stands in for urllib.request.urlopen and remembers the request body."""

    def __init__(self, response_text: str = "answer") -> None:
        self.response_text = response_text
        self.seen_body = None

    def __call__(self, req, timeout=None):
        self.seen_body = json.loads(req.data.decode()) if req.data else None
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"text": self.response_text}).encode()


@pytest.mark.asyncio
async def test_text_task_sends_no_image_b64(monkeypatch):
    """The crash this file exists to catch: b64encode(None) on a text task."""
    cap = _Capture()
    monkeypatch.setattr(
        "src.agents.manager.runner_client.urllib.request.urlopen", cap)

    client = RunnerClient("http://runner", token="t")
    out = await client.infer(None, "translate", prompt="текст")

    assert out == "answer"
    assert "image_b64" not in cap.seen_body
    assert cap.seen_body["task"] == "translate"
    assert cap.seen_body["prompt"] == "текст"


@pytest.mark.asyncio
async def test_image_task_still_encodes_the_image(monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(
        "src.agents.manager.runner_client.urllib.request.urlopen", cap)

    client = RunnerClient("http://runner")
    await client.infer(b"png-bytes", "vision")

    assert "image_b64" in cap.seen_body
    assert cap.seen_body["task"] == "vision"
