"""One generation at a time on the Runner's GPU (RFC 0022 §6).

The pool said inference was serialized, but it ran outside every lock: two
PageAgent requests in flight plus a timed-out client's retry ran
model.generate side by side on one T4, and "Programming the Z80" went seven
minutes without a single answer and without an error.
"""
import asyncio
import base64

import pytest
from fastapi.testclient import TestClient

from src.agents import router
from src.agents.runner.app import create_app
from src.agents.runner.config import RunnerConfig
from src.agents.runner.pool import Abandoned, ModelPool


class SlowLoader:
    """Records how many generations overlap and what limit each was given."""

    def __init__(self):
        self.name = "slow"
        self.tasks = ["vision", "translate"]
        self.vram_mb = 0
        self.loaded = False
        self.active = 0
        self.peak = 0
        self.limits = []

    async def load(self):
        self.loaded = True

    async def unload(self):
        self.loaded = False

    async def infer(self, image_png, task, prompt=None, max_new_tokens=None):
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.limits.append(max_new_tokens)
        await asyncio.sleep(0.02)
        self.active -= 1
        return "ok"


def pool_with(loader):
    pool = ModelPool()
    pool.register(loader)
    return pool


@pytest.mark.asyncio
async def test_generations_run_one_at_a_time():
    loader = SlowLoader()
    pool = pool_with(loader)
    await asyncio.gather(*(pool.infer("vision", b"png") for _ in range(4)))
    assert loader.peak == 1


@pytest.mark.asyncio
async def test_a_request_whose_client_left_is_not_generated():
    loader = SlowLoader()
    pool = pool_with(loader)

    async def gone():
        return False

    with pytest.raises(Abandoned):
        await pool.infer("vision", b"png", wanted=gone)
    assert loader.limits == []


@pytest.mark.asyncio
async def test_the_answer_limit_reaches_the_loader():
    loader = SlowLoader()
    pool = pool_with(loader)
    await pool.infer("translate", prompt="p", max_new_tokens=512)
    assert loader.limits == [512]


def test_infer_takes_an_answer_limit():
    app = create_app(RunnerConfig(token="", warmup_tasks=()), loaders=[SlowLoader()])
    with TestClient(app) as tc:
        res = tc.post("/infer", json={"task": "vision", "prompt": "p", "max_new_tokens": 300,
                                      "image_b64": base64.b64encode(b"png").decode()})
        assert res.status_code == 200
        assert app.state.pool._loaders["slow"].limits == [300]
        assert tc.post("/infer", json={"task": "translate", "prompt": "p",
                                       "max_new_tokens": 0}).status_code == 422


def test_call_infer_sends_the_limit(monkeypatch):
    seen = {}

    def fake_post(url, payload, headers, timeout=None, attempts=None):
        import json
        seen.update(json.loads(payload))
        return "ok", None

    monkeypatch.setattr(router, "_post_infer", fake_post)
    router.call_infer("http://gpu", "vision", b"png", prompt="p", max_new_tokens=1536)
    assert seen["max_new_tokens"] == 1536
