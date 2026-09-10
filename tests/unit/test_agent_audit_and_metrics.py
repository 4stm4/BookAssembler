"""Unit tests for Stage 5 of RFC 0022 — audit events + extended metrics.

Covers the shared AgentAudit adapter, Manager audit hooks
(MANAGER_STARTED / RUNNER_ANNOUNCED / AUTH_FAILED / INFER_COMPLETED /
INFER_FAILED), Manager metrics (auth_fail_total, announce_total,
announce_rejected_total), and Runner /metrics + audit
(RUNNER_STARTED / MODEL_LOADED).
"""

import base64
import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.agents.audit import AgentAudit
from src.agents.manager.app import create_app as make_manager
from src.agents.manager.config import ManagerConfig
from src.agents.runner.app import create_app as make_runner
from src.agents.runner.config import RunnerConfig
from src.agents.runner.loaders.base import EchoLoader


_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20).decode()


class FakeClient:
    def __init__(self, url: str, token: str = "") -> None: pass
    async def ready(self, timeout: float = 5.0) -> bool: return True
    async def health(self, timeout: float = 5.0) -> dict: return {"status": "ok"}
    async def infer(self, image_png, task, prompt=None, timeout=300.0) -> str:
        return f"ok:{task}"
    async def shutdown(self) -> None: return None


# ---------- AgentAudit ----------

def test_audit_writes_hash_chained_jsonl(tmp_path):
    a = AgentAudit("manager", log_dir=str(tmp_path))
    a.manager_started({"backend": "manual"})
    a.runner_announced("https://x.com", "up")
    a.infer_completed("table", 123, 4096)
    log_file = tmp_path / "audit.log"
    lines = [json.loads(x) for x in log_file.read_text().splitlines()]
    assert [r["event_type"] for r in lines] == [
        "MANAGER_STARTED", "RUNNER_ANNOUNCED", "INFER_COMPLETED",
    ]
    # Sequential seq + hash chain (each record's prev_hash is the previous line's sha256)
    assert [r["seq"] for r in lines] == [1, 2, 3]
    assert lines[0]["prev_hash"] == "0" * 64
    assert all(r["actor"] == "manager" for r in lines)


def test_audit_survives_bad_log_dir(monkeypatch, capsys):
    # Even if opening the log dir fails, audit calls must not raise.
    def bad_init(self, *a, **kw): raise OSError("read-only fs")

    from src.audit.logger import AuditLogger
    monkeypatch.setattr(AuditLogger, "__init__", bad_init)
    a = AgentAudit("manager", log_dir="/no/such/place")
    a.manager_started({})  # would raise if not guarded
    a.infer_failed("table", "boom")


# ---------- Manager audit + metrics ----------

@pytest.fixture
def manager_env(monkeypatch, tmp_path):
    audit = AgentAudit("manager", log_dir=str(tmp_path))
    cfg = ManagerConfig(kae_token="tok", runner_token="secret", backend="manual",
                        runner_static_url="http://127.0.0.1:5005",
                        announce_allow_local=True, announce_min_interval=1)
    from src.agents.manager import orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "RunnerClient", FakeClient)
    app = make_manager(cfg, audit=audit)
    return app, TestClient(app), audit, tmp_path


def _events(dir_path: Path) -> list:
    return [json.loads(x)["event_type"]
            for x in (dir_path / "audit.log").read_text().splitlines()]


def test_manager_start_emits_manager_started_event(manager_env):
    _, _, _, tmp = manager_env
    assert "MANAGER_STARTED" in _events(tmp)


def test_manager_auth_failure_is_audited_and_counted(manager_env):
    app, tc, _, tmp = manager_env
    # No Authorization header → 401 + AUTH_FAILED + auth_fail_total incremented.
    r = tc.post("/infer", json={"image_b64": _PNG, "task": "table"})
    assert r.status_code == 401
    events = _events(tmp)
    assert "AUTH_FAILED" in events
    assert app.state.metrics.auth_fail_total == 1


def test_manager_announce_audits_and_counts(manager_env):
    app, tc, _, tmp = manager_env
    r = tc.post("/runner/announce",
                json={"url": "http://127.0.0.1:5010", "secret": "secret"})
    assert r.status_code == 200
    assert "RUNNER_ANNOUNCED" in _events(tmp)
    assert app.state.metrics.announce_total == 1

    # Rate-limit rejection increments announce_rejected_total.
    r2 = tc.post("/runner/announce",
                 json={"url": "http://127.0.0.1:5011", "secret": "secret"})
    assert r2.status_code == 429
    assert app.state.metrics.announce_rejected_total == 1


def test_manager_infer_success_is_audited(manager_env):
    _, tc, _, tmp = manager_env
    r = tc.post("/infer", json={"image_b64": _PNG, "task": "table"},
                headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    events = _events(tmp)
    assert "INFER_COMPLETED" in events


def test_manager_infer_failure_is_audited(monkeypatch, tmp_path):
    class Broken(FakeClient):
        async def infer(self, image_png, task, prompt=None, timeout=300.0) -> str:
            raise RuntimeError("boom")

    audit = AgentAudit("manager", log_dir=str(tmp_path))
    cfg = ManagerConfig(kae_token="", runner_token="", backend="manual",
                        runner_static_url="http://fake", cooldown=0,
                        announce_allow_local=True)
    from src.agents.manager import orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "RunnerClient", Broken)
    app = make_manager(cfg, audit=audit)
    tc = TestClient(app)
    assert tc.post("/infer", json={"image_b64": _PNG,
                                   "task": "table"}).status_code == 503
    events = _events(tmp_path)
    assert "INFER_FAILED" in events


def test_manager_metrics_expose_new_counters(manager_env):
    _, tc, _, _ = manager_env
    tc.post("/infer", json={"image_b64": _PNG, "task": "table"})   # 401
    tc.post("/runner/announce",
            json={"url": "http://127.0.0.1:5020", "secret": "secret"})
    body = tc.get("/metrics").text
    for name in ("kae_auth_fail_total", "kae_announce_total",
                 "kae_announce_rejected_total"):
        assert name in body


# ---------- Runner audit + /metrics ----------

@pytest.fixture
def runner_client(tmp_path):
    audit = AgentAudit("runner", log_dir=str(tmp_path))
    cfg = RunnerConfig(token="", warmup_tasks=["table"], idle_timeout=0)
    app = make_runner(cfg,
                      loaders=[EchoLoader(name="echo", tasks=["table", "vision"],
                                          vram_mb=42)],
                      audit=audit)
    with TestClient(app) as tc:
        yield tc, tmp_path


def test_runner_start_and_warmup_are_audited(runner_client):
    _, tmp = runner_client
    events = [json.loads(x)["event_type"]
              for x in (tmp / "audit.log").read_text().splitlines()]
    assert "RUNNER_STARTED" in events
    assert "MODEL_LOADED" in events


def test_runner_metrics_endpoint_exposes_task_and_model_gauges(runner_client):
    tc, _ = runner_client
    tc.post("/infer", json={"image_b64": _PNG, "task": "vision"})
    body = tc.get("/metrics").text
    for name in ("kae_runner_up_seconds", "kae_runner_infer_total",
                 "kae_runner_vram_used_mb", "kae_runner_model_loads_total"):
        assert name in body
    assert 'kae_runner_infer_task_total{task="vision"}' in body
    assert 'kae_runner_model_loaded{name="echo"}' in body
