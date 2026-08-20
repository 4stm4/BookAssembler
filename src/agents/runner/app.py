"""
Runner FastAPI app (RFC 0022 §4.2).

Endpoints:
    GET  /health           # cheap, no model load
    GET  /ready            # 200 once the warmup set is loaded
    POST /infer            # {image_b64, task, prompt?} → {text}
    POST /ocr              # legacy alias, task='table'
    POST /shutdown         # graceful stop
    GET  /models           # {task→model, loaded[], vram_used_mb}
"""

import asyncio
import base64
import binascii
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from src.agents.audit import AgentAudit
from src.agents.runner.announce import announce_to_manager
from src.agents.runner.config import RunnerConfig
from src.agents.runner.idle import run_watchdog
from src.agents.runner.loaders.base import EchoLoader, ModelLoader
from src.agents.runner.metrics import RunnerMetrics, render as render_metrics
from src.agents.runner.pool import ModelPool

log = logging.getLogger(__name__)


class InferRequest(BaseModel):
    image_b64: str
    task: str
    prompt: Optional[str] = None


class OcrRequest(BaseModel):
    image_b64: str
    ocr_type: Optional[str] = "format"


def _decode_png(b64: str) -> bytes:
    try:
        return base64.b64decode(b64, validate=True)
    except binascii.Error as e:
        raise HTTPException(400, f"image_b64 is not valid base64: {e}") from e


def create_app(cfg: Optional[RunnerConfig] = None,
               loaders: Optional[List[ModelLoader]] = None,
               audit: Optional[AgentAudit] = None) -> FastAPI:
    """Build a Runner app.

    `loaders` — the real loaders (Qwen2.5-VL, GOT-OCR, ...). If None, an
    EchoLoader is registered so tests and dev-mode notebooks work without a GPU.
    """
    cfg = cfg or RunnerConfig()
    audit = audit or AgentAudit("runner")
    metrics = RunnerMetrics()
    pool = ModelPool(vram_budget_mb=cfg.vram_budget_mb)
    for ldr in (loaders or [EchoLoader()]):
        pool.register(ldr)

    state = {"last_request_at": time.time(), "in_flight": 0, "ready": False}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        audit.runner_started(warmup=list(cfg.warmup_tasks))
        # Warmup declared set (RFC 0022 §5.3).
        for task in cfg.warmup_tasks:
            try:
                loader = await pool.ensure_loaded(task)
                metrics.model_loads_total += 1
                audit.model_loaded(loader.name, loader.vram_mb)
            except Exception as e:
                log.exception("warmup of task %r failed", task)
                audit.runner_error(f"warmup {task}: {e}")
        state["ready"] = True

        # Push discovery (RFC 0022 §5.2).
        if cfg.manager_url and cfg.public_url:
            asyncio.create_task(announce_to_manager(
                cfg.manager_url, cfg.public_url, cfg.token))

        # Idle self-shutdown (RFC 0022 §9.4).
        asyncio.create_task(run_watchdog(
            cfg.idle_timeout,
            get_last_request_ts=lambda: state["last_request_at"],
            is_busy=lambda: state["in_flight"] > 0,
        ))
        yield

    app = FastAPI(title="KAE GPU Runner", version="0.1.0", lifespan=lifespan)

    def _require_token(authorization: Optional[str] = Header(default=None)) -> None:
        if not cfg.token:
            return
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing Bearer token")
        if authorization.removeprefix("Bearer ").strip() != cfg.token:
            raise HTTPException(401, "Bad Bearer token")

    def _bump() -> None:
        state["last_request_at"] = time.time()

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "kind": "runner",
            "tasks": pool.tasks(),
            "models_loaded": pool.loaded_names(),
            "vram_used_mb": pool.vram_used_mb(),
            "ready": state["ready"],
        }

    @app.get("/ready")
    async def ready() -> dict:
        if not state["ready"]:
            raise HTTPException(503, "warming up")
        return {"ready": True}

    @app.get("/models")
    async def models() -> dict:
        return {
            "tasks": {task: pool._by_task[task].name for task in pool.tasks()},
            "loaded": pool.loaded_names(),
            "vram_used_mb": pool.vram_used_mb(),
            "vram_budget_mb": pool.vram_budget_mb,
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics_endpoint() -> str:
        return render_metrics(metrics, pool.loaded_names(), pool.vram_used_mb())

    async def _do_infer(task: str, png: bytes, prompt: Optional[str]) -> str:
        state["in_flight"] += 1
        t0 = time.time()
        ok = False
        try:
            _bump()
            text = await pool.infer(task, png, prompt=prompt)
            _bump()
            ok = True
            return text
        except KeyError as e:
            raise HTTPException(400, str(e)) from e
        finally:
            duration = time.time() - t0
            metrics.record_infer(task, duration, ok)
            state["in_flight"] -= 1

    @app.post("/infer", dependencies=[Depends(_require_token)])
    async def infer(body: InferRequest) -> dict:
        png = _decode_png(body.image_b64)
        text = await _do_infer(body.task, png, body.prompt)
        return {"text": text}

    @app.post("/ocr", dependencies=[Depends(_require_token)])
    async def ocr(body: OcrRequest) -> dict:
        png = _decode_png(body.image_b64)
        text = await _do_infer("table", png, None)
        return {"text": text}

    @app.post("/shutdown", dependencies=[Depends(_require_token)])
    async def shutdown() -> dict:
        log.warning("Shutdown requested — exiting in 200ms")
        asyncio.get_event_loop().call_later(0.2, lambda: os._exit(0))
        return {"status": "stopping"}

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled: %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    app.state.cfg = cfg
    app.state.pool = pool
    app.state.runner_state = state
    app.state.audit = audit
    app.state.metrics = metrics
    return app
