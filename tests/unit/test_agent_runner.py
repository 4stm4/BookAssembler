"""Unit tests for the GPU Runner (RFC 0022 §4.2, §6).

No GPU, no real models — uses `EchoLoader` and tiny fakes.
"""

import asyncio
import base64
import time

import pytest
from fastapi.testclient import TestClient

from src.agents.runner.app import create_app
from src.agents.runner.config import RunnerConfig
from src.agents.runner.idle import run_watchdog
from src.agents.runner.loaders.base import EchoLoader
from src.agents.runner.pool import ModelPool


_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20).decode()


# ---------- ModelPool ----------

@pytest.mark.asyncio
async def test_pool_lazy_load_and_dispatch_by_task():
    pool = ModelPool()
    pool.register(EchoLoader(name="e", tasks=["table", "vision"], vram_mb=100))
    assert pool.loaded_names() == []
    text = await pool.infer("table", b"png")
    assert text == "echo(e):table:3"
    assert pool.loaded_names() == ["e"]


@pytest.mark.asyncio
async def test_pool_rejects_unknown_task():
    pool = ModelPool()
    pool.register(EchoLoader(name="e", tasks=["table"]))
    with pytest.raises(KeyError):
        await pool.infer("formula", b"png")


@pytest.mark.asyncio
async def test_pool_evicts_lru_under_budget():
    pool = ModelPool(vram_budget_mb=150)
    a = EchoLoader(name="A", tasks=["table"], vram_mb=100)
    b = EchoLoader(name="B", tasks=["vision"], vram_mb=100)
    pool.register(a)
    pool.register(b)
    await pool.infer("table", b"1")           # loads A (100/150)
    assert pool.loaded_names() == ["A"]
    await asyncio.sleep(0.01)                 # bump lru order
    await pool.infer("vision", b"22")         # loads B; A must be evicted
    assert pool.loaded_names() == ["B"]
    assert pool.vram_used_mb() == 100


@pytest.mark.asyncio
async def test_pool_rebinding_same_task_to_new_loader_is_rejected():
    pool = ModelPool()
    pool.register(EchoLoader(name="X", tasks=["table"]))
    with pytest.raises(ValueError):
        pool.register(EchoLoader(name="Y", tasks=["table"]))


# ---------- HTTP ----------

@pytest.fixture
def client():
    cfg = RunnerConfig(token="", warmup_tasks=["table"], idle_timeout=0)
    app = create_app(cfg, loaders=[EchoLoader(name="echo",
                                              tasks=["table", "vision"])])
    # Enter TestClient as a context manager so FastAPI runs the lifespan
    # (startup/shutdown) — that's what flips `ready` after warmup.
    with TestClient(app) as tc:
        yield tc


def test_health_reports_tasks_and_ready_after_warmup(client):
    h = client.get("/health").json()
    assert h["status"] == "ok"
    assert h["kind"] == "runner"
    assert "table" in h["tasks"]
    assert h["ready"] is True
    assert "echo" in h["models_loaded"]


def test_ready_returns_ok_after_warmup(client):
    assert client.get("/ready").status_code == 200


def test_infer_returns_echo(client):
    r = client.post("/infer", json={"image_b64": _PNG, "task": "vision"})
    assert r.status_code == 200
    assert r.json()["text"].startswith("echo(echo):vision:")


def test_infer_rejects_unknown_task(client):
    r = client.post("/infer", json={"image_b64": _PNG, "task": "nope"})
    assert r.status_code == 400


def test_infer_rejects_bad_base64(client):
    r = client.post("/infer", json={"image_b64": "!!!bad!!!", "task": "table"})
    assert r.status_code == 400


def test_ocr_alias_uses_table_task(client):
    r = client.post("/ocr", json={"image_b64": _PNG})
    assert r.status_code == 200
    assert ":table:" in r.json()["text"]


def test_models_endpoint_exposes_registry(client):
    m = client.get("/models").json()
    assert m["tasks"] == {"table": "echo", "vision": "echo"}
    assert m["vram_budget_mb"] == 0


def test_bearer_auth_enforced(monkeypatch):
    cfg = RunnerConfig(token="topsecret", warmup_tasks=[], idle_timeout=0)
    with TestClient(create_app(cfg, loaders=[EchoLoader()])) as tc:
        assert tc.post("/infer", json={"image_b64": _PNG,
                                       "task": "table"}).status_code == 401
        ok = tc.post("/infer", json={"image_b64": _PNG, "task": "table"},
                     headers={"Authorization": "Bearer topsecret"})
        assert ok.status_code == 200


# ---------- Idle watchdog ----------

@pytest.mark.asyncio
async def test_idle_watchdog_triggers_exit_after_timeout():
    """Watchdog calls the injected _exit when idle_timeout elapses w/o traffic."""
    exit_calls: list = []

    def fake_exit(code: int) -> None:
        exit_calls.append(code)
        raise SystemExit(code)  # unwind the loop

    with pytest.raises(SystemExit):
        await run_watchdog(
            idle_timeout=1,
            get_last_request_ts=lambda: time.time() - 5,  # already idle
            is_busy=lambda: False,
            check_interval=0.05,
            _exit=fake_exit,
        )
    assert exit_calls == [0]


@pytest.mark.asyncio
async def test_idle_watchdog_skips_when_busy():
    """When traffic is active the watchdog must NOT exit."""
    called: list = []

    async def run_briefly() -> None:
        task = asyncio.create_task(run_watchdog(
            idle_timeout=1,
            get_last_request_ts=lambda: time.time(),
            is_busy=lambda: True,
            check_interval=0.05,
            _exit=lambda code: called.append(code),
        ))
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await run_briefly()
    assert called == []



# ---------- payload contract (RFC 0022 v1.2.0 §4.4) ----------
# image_b64 used to be a required field, so `refine` and `translate` could not
# reach the GPU at all and ran on the rpi5 CPU while the card sat idle.

@pytest.fixture
def any_task_client():
    from src.agents.tasks import ALL_TASKS
    cfg = RunnerConfig(token="", warmup_tasks=[], idle_timeout=0)
    app = create_app(cfg, loaders=[EchoLoader(name="echo",
                                              tasks=list(ALL_TASKS))])
    with TestClient(app) as tc:
        yield tc


def test_text_task_runs_without_an_image(any_task_client):
    r = any_task_client.post("/infer",
                             json={"task": "translate", "prompt": "текст"})
    assert r.status_code == 200, r.text
    assert "translate" in r.json()["text"]


def test_image_task_without_an_image_is_400(any_task_client):
    r = any_task_client.post("/infer", json={"task": "ocr"})
    assert r.status_code == 400
    assert "needs image_b64" in r.json()["detail"]


def test_text_task_without_a_prompt_is_400(any_task_client):
    r = any_task_client.post("/infer", json={"task": "refine"})
    assert r.status_code == 400
    assert "needs a prompt" in r.json()["detail"]


def test_text_task_carrying_an_image_is_400(any_task_client):
    """A page image sent to translate would burn a GPU slot silently."""
    png = base64.b64encode(b"page").decode()
    r = any_task_client.post("/infer", json={
        "task": "refine", "prompt": "x", "image_b64": png})
    assert r.status_code == 400
    assert "text-only" in r.json()["detail"]


def test_unknown_task_is_named_in_the_error(any_task_client):
    r = any_task_client.post("/infer", json={"task": "summarise",
                                            "prompt": "x"})
    assert r.status_code == 400
    assert "unknown task" in r.json()["detail"]
    assert "summarise" in r.json()["detail"]


def test_image_task_is_unaffected(any_task_client):
    png = base64.b64encode(b"not-really-a-png").decode()
    r = any_task_client.post("/infer", json={"task": "vision",
                                            "image_b64": png})
    assert r.status_code == 200, r.text
