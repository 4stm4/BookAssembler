"""
Manager FastAPI app (RFC 0022 §4.1). Public API for KAE agents-manager.

Endpoints:
    GET  /health                  # for KAE agent-manager probe
    POST /infer   {image_b64, task, prompt?}
    POST /ocr     {image_b64, ocr_type?}          # legacy alias for GOT-OCR clients
    POST /runner/announce  {url, secret}          # Runner discovers itself here
    GET  /metrics                 # Prometheus text exposition

Auth (Bearer): two independent tokens, KAE→Manager and Manager→Runner. See RFC.
"""

import base64
import binascii
import logging
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from src.agents.manager.backends.base import ManualBackend, RunnerBackend
from src.agents.manager.config import ManagerConfig
from src.agents.manager.metrics import Metrics, render
from src.agents.manager.orchestrator import Orchestrator
from src.agents.manager.state import ManagerState, RunnerStatus

log = logging.getLogger(__name__)


class InferRequest(BaseModel):
    image_b64: str
    task: str
    prompt: Optional[str] = None


class OcrRequest(BaseModel):
    image_b64: str
    ocr_type: Optional[str] = "format"


class AnnounceRequest(BaseModel):
    url: str
    secret: str


def _decode_png(image_b64: str) -> bytes:
    try:
        return base64.b64decode(image_b64, validate=True)
    except binascii.Error as e:
        raise HTTPException(400, f"image_b64 is not valid base64: {e}") from e


def _pick_backend(cfg: ManagerConfig) -> RunnerBackend:
    kind = (cfg.backend or "manual").lower()
    if kind == "manual":
        return ManualBackend()
    if kind == "kaggle":
        # Imported lazily — the `kaggle` package is an optional runtime dep.
        from src.agents.manager.backends.kaggle import KaggleKernelBackend
        return KaggleKernelBackend(kernel=cfg.kaggle_kernel, kernel_dir=cfg.kaggle_kernel_dir)
    raise ValueError(f"Unknown backend: {cfg.backend!r}")


def create_app(cfg: Optional[ManagerConfig] = None) -> FastAPI:
    cfg = cfg or ManagerConfig()
    state = ManagerState()
    backend = _pick_backend(cfg)
    orch = Orchestrator(cfg, state, backend)
    metrics = Metrics()

    # Seed the state from a static runner URL if operator provided one.
    if cfg.runner_static_url:
        # No await here — startup event does it properly.
        state.runner_url = cfg.runner_static_url

    app = FastAPI(title="KAE GPU Runner Manager", version="0.1.0")

    # ---- auth ----
    def _require_kae_token(authorization: Optional[str] = Header(default=None)) -> None:
        if not cfg.kae_token:
            return  # no token configured — dev mode
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing Bearer token")
        if authorization.removeprefix("Bearer ").strip() != cfg.kae_token:
            raise HTTPException(401, "Bad Bearer token")

    def _require_announce_secret(secret: str) -> None:
        # Announce uses the Runner-side token as the shared secret so the Runner
        # can prove it's ours (RFC 0022 §5.2 push-announce).
        if not cfg.runner_token:
            return
        if secret != cfg.runner_token:
            raise HTTPException(401, "Bad announce secret")

    # In-flight counter behaves as both queue depth and back-pressure gate.
    # Guarded by an asyncio.Lock to survive concurrent /infer calls.
    import asyncio as _asyncio
    inflight_lock = _asyncio.Lock()
    inflight_state = {"n": 0}

    async def _queue_depth() -> int:
        return inflight_state["n"]

    # ---- endpoints ----
    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "kind": "managed",
            "tasks": cfg.roles,
            "runner": state.status.value,
            "runner_url": state.runner_url,
            "queue_depth": await _queue_depth(),
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics_endpoint() -> str:
        return render(metrics, state.snapshot_gpu_seconds(), await _queue_depth())

    @app.post("/runner/announce")
    async def announce(body: AnnounceRequest) -> dict:
        _require_announce_secret(body.secret)
        await state.announce_runner(body.url)
        # Optimistic: probe once inline so we can flip to WARMING / UP quickly.
        cli = orch.client()
        if cli:
            try:
                if await cli.ready(timeout=3.0):
                    await state.set_status(RunnerStatus.UP)
                else:
                    await state.set_status(RunnerStatus.WARMING)
            except Exception:
                await state.set_status(RunnerStatus.WARMING)
        log.info("Runner announced at %s (status=%s)", body.url, state.status.value)
        return {"status": "accepted", "url": body.url}

    async def _run_infer(task: str, image_png: bytes, prompt: Optional[str]) -> str:
        # Back-pressure: bail early if we're already at capacity.
        async with inflight_lock:
            if inflight_state["n"] >= cfg.max_queue:
                raise HTTPException(429, "Manager queue is full; retry later",
                                    headers={"Retry-After": "10"})
            inflight_state["n"] += 1
            metrics.observe_queue(inflight_state["n"])

        t0 = time.time()
        ok = False
        try:
            client = await orch.ensure_ready()
            text = await client.infer(image_png, task, prompt=prompt,
                                      timeout=cfg.infer_timeout)
            await state.mark_infer_ok()
            ok = True
            return text
        except HTTPException:
            raise
        except TimeoutError as e:
            await orch.note_infer_error(str(e))
            raise HTTPException(504, f"Runner timeout: {e}") from e
        except Exception as e:
            await orch.note_infer_error(str(e))
            log.exception("infer failed")
            raise HTTPException(503, f"Runner error: {e}") from e
        finally:
            metrics.record_infer(task, time.time() - t0, ok)
            async with inflight_lock:
                inflight_state["n"] -= 1

    @app.post("/infer", dependencies=[Depends(_require_kae_token)])
    async def infer(body: InferRequest) -> dict:
        png = _decode_png(body.image_b64)
        text = await _run_infer(body.task, png, body.prompt)
        return {"text": text}

    @app.post("/ocr", dependencies=[Depends(_require_kae_token)])
    async def ocr(body: OcrRequest) -> dict:
        """Legacy alias for GOT-OCR clients — always uses task='table'."""
        png = _decode_png(body.image_b64)
        text = await _run_infer("table", png, None)
        return {"text": text}

    # Prevent silent failures being swallowed by fastapi default handler.
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled: %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    app.state.cfg = cfg
    app.state.manager_state = state
    app.state.orchestrator = orch
    app.state.metrics = metrics
    return app
