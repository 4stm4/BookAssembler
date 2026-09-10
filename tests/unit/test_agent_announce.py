"""Unit tests for Stage 4 of RFC 0022 — /runner/announce hardening.

Covers URL validation, endpoint auth + rate-limit + idempotency, and the
Runner-side retry policy in announce_to_manager().
"""

import asyncio
import base64
import pytest
from fastapi.testclient import TestClient

from src.agents.manager.announce_validation import AnnounceUrlError, validate_runner_url
from src.agents.manager.app import create_app
from src.agents.manager.config import ManagerConfig
from src.agents.runner.announce import announce_to_manager


# ---------- URL validation ----------

@pytest.mark.parametrize("url", [
    "https://foo.trycloudflare.com",
    "https://runner.example.com:8443",
    "http://kae-runner.io:5005",
])
def test_validate_accepts_public_urls(url):
    got = validate_runner_url(url)
    assert got.startswith(("http://", "https://"))


@pytest.mark.parametrize("url", [
    "",
    "ftp://foo.com",
    "not-a-url",
    "https://",
    "https://127.0.0.1",
    "http://localhost:8080",
    "https://host.local",
    "http://10.0.0.5",         # private RFC1918
    "http://192.168.1.10",     # private RFC1918
    "http://169.254.10.1",     # link-local
    "https://[::1]",           # IPv6 loopback
    "http://224.0.0.1",        # multicast
    "http://0.0.0.0",          # unspecified
])
def test_validate_rejects_bad_or_private_urls(url):
    with pytest.raises(AnnounceUrlError):
        validate_runner_url(url)


def test_validate_allows_local_when_flagged():
    # Loopback is allowed only when explicitly asked (tests / dev).
    assert validate_runner_url("http://127.0.0.1:5005", allow_local=True) \
        == "http://127.0.0.1:5005"
    assert validate_runner_url("http://localhost:5005", allow_local=True) \
        == "http://localhost:5005"


def test_validate_strips_path_and_query():
    got = validate_runner_url("https://runner.example.com/path?x=1#f")
    assert got == "https://runner.example.com"


# ---------- Manager /runner/announce endpoint ----------

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20).decode()


class FakeClient:
    def __init__(self, url: str, token: str = "") -> None:
        self.url = url
        self.token = token

    async def ready(self, timeout: float = 5.0) -> bool:
        return True

    async def health(self, timeout: float = 5.0) -> dict:
        return {"status": "ok"}

    async def infer(self, image_png, task, prompt=None, timeout=300.0) -> str:
        return "ok"

    async def shutdown(self) -> None:
        return None


def _make_client(**cfg_kwargs):
    cfg = ManagerConfig(
        kae_token="", runner_token="secret", backend="manual",
        announce_allow_local=True,   # tests use loopback URLs
        announce_min_interval=1,
        **cfg_kwargs,
    )
    app = create_app(cfg)
    from src.agents.manager import orchestrator as orch_mod
    # Substitute RunnerClient so the optimistic probe returns True.
    import src.agents.manager.app as app_mod
    orch_mod.RunnerClient = FakeClient
    app_mod.RunnerClient = FakeClient  # some paths import it here too
    return TestClient(app)


def test_announce_rejects_bad_url():
    tc = _make_client()
    r = tc.post("/runner/announce",
                json={"url": "not-a-url", "secret": "secret"})
    assert r.status_code == 400


def test_announce_rejects_private_url_by_default(monkeypatch):
    # Same client but with allow_local=False (production default).
    cfg = ManagerConfig(kae_token="", runner_token="secret", backend="manual",
                        announce_allow_local=False, announce_min_interval=0)
    app = create_app(cfg)
    from src.agents.manager import orchestrator as orch_mod
    orch_mod.RunnerClient = FakeClient
    tc = TestClient(app)
    r = tc.post("/runner/announce",
                json={"url": "http://192.168.1.5:5005", "secret": "secret"})
    assert r.status_code == 400


def test_announce_rejects_bad_secret():
    tc = _make_client()
    r = tc.post("/runner/announce",
                json={"url": "http://127.0.0.1:5005", "secret": "wrong"})
    assert r.status_code == 401


def test_announce_accepts_and_returns_normalised_url():
    tc = _make_client()
    r = tc.post("/runner/announce",
                json={"url": "http://127.0.0.1:5005/ignored?x=1", "secret": "secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "http://127.0.0.1:5005"
    assert body["status"] == "accepted"


def test_announce_same_url_is_idempotent():
    tc = _make_client()
    first = tc.post("/runner/announce",
                    json={"url": "http://127.0.0.1:5005", "secret": "secret"})
    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    # Immediate repeat with SAME url → not rate-limited, status=unchanged.
    second = tc.post("/runner/announce",
                     json={"url": "http://127.0.0.1:5005", "secret": "secret"})
    assert second.status_code == 200
    assert second.json()["status"] == "unchanged"


def test_announce_rate_limits_different_urls():
    tc = _make_client()
    a = tc.post("/runner/announce",
                json={"url": "http://127.0.0.1:5005", "secret": "secret"})
    assert a.status_code == 200
    # Different URL immediately → hits rate-limit.
    b = tc.post("/runner/announce",
                json={"url": "http://127.0.0.1:5006", "secret": "secret"})
    assert b.status_code == 429
    assert b.headers.get("Retry-After") == "1"


# ---------- Runner-side retry ----------

@pytest.mark.asyncio
async def test_announce_to_manager_returns_true_on_2xx(monkeypatch):
    from src.agents.runner import announce as announce_mod
    calls: list = []

    def fake_post(url, body, timeout):
        calls.append(url)
        return 200

    monkeypatch.setattr(announce_mod, "_post_once", fake_post)
    ok = await announce_to_manager("http://manager", "http://runner", "s")
    assert ok is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_announce_to_manager_retries_then_succeeds(monkeypatch):
    from src.agents.runner import announce as announce_mod
    seq = iter([0, 502, 429, 200])          # network err, then 5xx, then 429, then ok

    def fake_post(url, body, timeout):
        return next(seq)

    monkeypatch.setattr(announce_mod, "_post_once", fake_post)
    async def _no_sleep(*_a, **_kw):
        return None
    monkeypatch.setattr(announce_mod.asyncio, "sleep", _no_sleep)
    ok = await announce_to_manager("http://manager", "http://runner", "s",
                                   max_attempts=6, initial_backoff=0.01)
    assert ok is True


@pytest.mark.asyncio
async def test_announce_to_manager_gives_up_on_4xx_not_429(monkeypatch):
    from src.agents.runner import announce as announce_mod
    calls: list = []

    def fake_post(url, body, timeout):
        calls.append(url)
        return 400

    monkeypatch.setattr(announce_mod, "_post_once", fake_post)
    ok = await announce_to_manager("http://manager", "http://runner", "s",
                                   max_attempts=5, initial_backoff=0.01)
    assert ok is False
    # A 4xx that isn't 429 must NOT be retried.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_announce_to_manager_gives_up_after_max_attempts(monkeypatch):
    from src.agents.runner import announce as announce_mod
    calls: list = []

    def fake_post(url, body, timeout):
        calls.append(url); return 502

    monkeypatch.setattr(announce_mod, "_post_once", fake_post)
    async def _no_sleep(*_a, **_kw):
        return None
    monkeypatch.setattr(announce_mod.asyncio, "sleep", _no_sleep)
    ok = await announce_to_manager("http://manager", "http://runner", "s",
                                   max_attempts=3, initial_backoff=0.01)
    assert ok is False
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_announce_to_manager_no_op_without_manager_url():
    # Empty manager_url = "announce disabled" — must not raise, must not retry.
    ok = await announce_to_manager("", "http://runner", "s")
    assert ok is False
