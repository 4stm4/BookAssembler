"""Unit tests for the GPU Runner Manager (RFC 0022 §4/§5).

These tests use FastAPI's TestClient and mock the Runner via monkey-patching
RunnerClient; no network / GPU / Kaggle required.
"""

import base64
import pytest
from fastapi.testclient import TestClient

from src.agents.manager import RunnerStatus
from src.agents.manager.app import create_app
from src.agents.manager.config import ManagerConfig


_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20).decode()


class FakeClient:
    def __init__(self, url: str, token: str = "") -> None:
        self.url = url
        self.token = token

    async def health(self, timeout: float = 5.0) -> dict:
        return {"status": "ok", "kind": "runner"}

    async def ready(self, timeout: float = 5.0) -> bool:
        return True

    async def infer(self, image_png, task, prompt=None, timeout=300.0) -> str:
        # A text task carries no image (RFC 0022 §4.4), so len() would raise.
        return f"echo:{task}:{len(image_png or b'')}"

    async def shutdown(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch):
    # No auth for these tests; use a "manual" backend with a static URL.
    cfg = ManagerConfig(kae_token="", runner_token="",
                        backend="manual", runner_static_url="http://fake-runner")
    app = create_app(cfg)
    # Every RunnerClient(...) constructor made from the orchestrator or announce
    # handler is replaced with our FakeClient.
    from src.agents.manager import orchestrator as orch_mod
    from src.agents.manager import app as app_mod
    monkeypatch.setattr(orch_mod, "RunnerClient", FakeClient)
    monkeypatch.setattr(app_mod, "RunnerClient", FakeClient, raising=False)
    return TestClient(app)


def test_health_reports_roles_and_runner_status(client):
    r = client.get("/health").json()
    assert r["status"] == "ok"
    assert r["kind"] == "managed"
    assert set(r["tasks"]) >= {"table"}  # default roles
    assert "runner" in r


def test_infer_happy_path_delegates_to_runner(client):
    r = client.post("/infer", json={"image_b64": _PNG, "task": "table"})
    assert r.status_code == 200, r.text
    assert r.json()["text"].startswith("echo:table:")


def test_infer_rejects_bad_base64(client):
    r = client.post("/infer", json={"image_b64": "!!!not-base64!!!", "task": "table"})
    assert r.status_code == 400


def test_ocr_alias_uses_table_task(client):
    r = client.post("/ocr", json={"image_b64": _PNG})
    assert r.status_code == 200
    assert "echo:table:" in r.json()["text"]


def test_metrics_exposes_gpu_seconds_and_counters(client):
    client.post("/infer", json={"image_b64": _PNG, "task": "vision"})
    text = client.get("/metrics").text
    for name in ("kae_gpu_seconds_used", "kae_infer_total",
                 "kae_manager_up_seconds", "kae_queue_depth"):
        assert name in text, f"missing metric: {name}"
    assert 'kae_infer_task_total{task="vision"}' in text


def test_announce_updates_runner_url(client):
    r = client.post("/runner/announce",
                    json={"url": "http://new-runner", "secret": ""})
    assert r.status_code == 200
    assert r.json()["url"] == "http://new-runner"
    h = client.get("/health").json()
    assert h["runner_url"] == "http://new-runner"


def test_auth_enforced_when_token_configured(monkeypatch):
    cfg = ManagerConfig(kae_token="s3cret", runner_token="",
                        backend="manual", runner_static_url="http://fake-runner")
    app = create_app(cfg)
    from src.agents.manager import orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "RunnerClient", FakeClient)
    tc = TestClient(app)

    r = tc.post("/infer", json={"image_b64": _PNG, "task": "table"})
    assert r.status_code == 401

    r = tc.post("/infer", json={"image_b64": _PNG, "task": "table"},
                headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_state_machine_transitions_up_to_error_on_repeated_failures(monkeypatch):
    """3 consecutive infer failures → orchestrator sets state ERROR and cools."""
    class Broken(FakeClient):
        async def infer(self, image_png, task, prompt=None, timeout=300.0) -> str:
            raise RuntimeError("boom")

    cfg = ManagerConfig(kae_token="", runner_token="",
                        backend="manual", runner_static_url="http://fake",
                        cooldown=0)  # avoid the actual sleep in test
    app = create_app(cfg)
    from src.agents.manager import orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "RunnerClient", Broken)
    tc = TestClient(app)
    for _ in range(3):
        assert tc.post("/infer", json={"image_b64": _PNG, "task": "table"}).status_code == 503
    # After 3 errors we're at least in an error/cold-ish state.
    h = tc.get("/health").json()
    assert h["runner"] in {RunnerStatus.ERROR.value, RunnerStatus.COLD.value,
                           RunnerStatus.STOPPING.value}


# --- text tasks, priority and the bulk budget (RFC 0022 v1.2.0) ------------


def test_text_task_reaches_the_runner_without_an_image(client):
    r = client.post("/infer", json={"task": "translate", "prompt": "текст"})
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "echo:translate:0"


def test_image_task_without_an_image_is_400(client):
    r = client.post("/infer", json={"task": "ocr"})
    assert r.status_code == 400
    assert "needs image_b64" in r.json()["detail"]


def test_text_task_without_a_prompt_is_400(client):
    r = client.post("/infer", json={"task": "refine"})
    assert r.status_code == 400
    assert "needs a prompt" in r.json()["detail"]


def test_client_priority_is_clamped_not_trusted(client, monkeypatch):
    """§9 inv.8: a caller cannot label its bulk work interactive."""
    from src.agents.manager import app as app_mod
    seen = {}
    real = app_mod.clamp_priority
    monkeypatch.setattr(app_mod, "clamp_priority",
                        lambda t, p: seen.setdefault("out", real(t, p)))
    client.post("/infer", json={"task": "translate", "prompt": "x",
                                "priority": 0})
    from src.agents.tasks import Priority
    assert seen["out"] == Priority.BULK


def test_queue_wait_is_reported_per_priority(client):
    client.post("/infer", json={"task": "translate", "prompt": "x"})
    text = client.get("/metrics").text
    assert "kae_queue_wait_seconds_avg" in text
    assert 'kae_infer_priority_total{priority="3"}' in text


def test_exhausted_bulk_budget_refuses_bulk_but_not_ocr(client):
    """§7.2: running out of the bulk budget must never refuse OCR.

    A page with no text at all is worse than a page left untranslated.
    """
    app = client.app
    app.state.metrics.bulk_seconds_used = 10 ** 9

    bulk = client.post("/infer", json={"task": "translate", "prompt": "x"})
    assert bulk.status_code == 429
    assert "edge cluster" in bulk.json()["detail"]
    assert bulk.headers["Retry-After"] == "3600"

    ocr = client.post("/infer", json={"task": "ocr", "image_b64": _PNG})
    assert ocr.status_code == 200, ocr.text
    assert ocr.json()["text"].startswith("echo:ocr:")
