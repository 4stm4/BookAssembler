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
        return f"echo:{task}:{len(image_png)}"

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
