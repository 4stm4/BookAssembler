"""
Agent router — shared helpers for role-based agent routing.

Reads the agent-manager config (persisted by the API) and picks a reachable
agent for a given role. Used by both the REST layer and pipeline analyzers so
routing rules stay in one place.
"""

import base64
import json
import logging
import os
import urllib.request
from typing import Any, List, Optional, Tuple

log = logging.getLogger(__name__)

# Must match src/api/app.py — same file the agent-manager REST layer writes.
AGENTS_CONFIG_PATH = os.path.join(
    os.environ.get("KAE_SSD_PATH", "/data/kae"), "agents.json"
)
# Fallback if env is different at write vs read time (legacy /data/kae).
_LEGACY_PATH = "/data/kae/agents.json"


def load_agents() -> List[dict]:
    for p in (AGENTS_CONFIG_PATH, _LEGACY_PATH):
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    return []


def _probe_ollama(host: str) -> Tuple[bool, List[str]]:
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
            return True, [m["name"] for m in data.get("models", [])]
    except Exception:
        return False, []


def _probe_health(host: str) -> Tuple[bool, List[str]]:
    try:
        req = urllib.request.Request(f"{host}/health")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            return True, data.get("tasks") or [data.get("model", "")]
    except Exception:
        return False, []


def probe_managed(host: str) -> Tuple[bool, dict]:
    """/health of a Manager (RFC 0022 §4.1). Returns (reachable, health_body).

    Health body carries tasks, runner state, runner_url, queue_depth so the KAE
    agent-manager UI can render a live indicator (Stage 6).
    """
    try:
        req = urllib.request.Request(f"{host}/health")
        with urllib.request.urlopen(req, timeout=5) as r:
            return True, json.loads(r.read())
    except Exception:
        return False, {}


_VISION_ROLES = {"table", "formula", "vision"}


def pick(role: str) -> Tuple[Optional[str], Optional[str], str]:
    """Return (host, model, kind) of the first reachable agent with `role`.

    Vision roles (table/formula/vision) require an agent that actually declares
    them — an ollama fallback can't do OCR/vision. Text roles fall back to any
    reachable ollama so existing translate/refine paths keep working.
    """
    for a in load_agents():
        if role not in (a.get("roles") or []):
            continue
        kind = a.get("kind", "ollama")
        if kind == "managed":
            ok, health = probe_managed(a["host"])
            # Manager is reachable ≠ Runner is ready. Only route inference here
            # when the Runner is UP; otherwise the request would sit in queue.
            if ok and health.get("runner") == "up":
                tasks = health.get("tasks") or []
                return a["host"], (a.get("active_model")
                                   or (tasks[0] if tasks else None)), kind
            continue
        ok, models = (_probe_health if kind in ("got-ocr", "multimodel") else _probe_ollama)(a["host"])
        if ok:
            return a["host"], (a.get("active_model") or (models[0] if models else None)), kind
    if role in _VISION_ROLES:
        return None, None, ""
    for a in load_agents():
        if a.get("kind", "ollama") == "ollama":
            ok, models = _probe_ollama(a["host"])
            if ok:
                return a["host"], (a.get("active_model") or (models[0] if models else None)), "ollama"
    return None, None, "ollama"


def _token_for_host(host: str) -> Optional[str]:
    """Look up Bearer token for a host from agents.json."""
    for a in load_agents():
        if a.get("host", "").rstrip("/") == host.rstrip("/"):
            return a.get("token")
    return None


def call_infer(
    host: str, task: str, image_png: bytes,
    prompt: Optional[str] = None, kind: str = "multimodel",
    model: Optional[str] = None,
) -> Optional[str]:
    """Send an image to an agent for inference. Supports multimodel, got-ocr, and ollama."""
    b64 = base64.b64encode(image_png).decode()

    if kind == "ollama":
        body = {
            "model": model or "llava:7b",
            "prompt": prompt or f"Describe this image for {task}.",
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.0, "seed": 42},
        }
        payload = json.dumps(body).encode()
        try:
            req = urllib.request.Request(
                f"{host}/api/generate", data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read()).get("response", "")
        except Exception as exc:
            log.warning("ollama vision %s failed: %s", host, exc)
            return None

    body = {"image_b64": b64, "task": task}
    if prompt:
        body["prompt"] = prompt
    payload = json.dumps(body).encode()
    headers: dict = {"Content-Type": "application/json"}
    token = _token_for_host(host)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for path in ("/infer", "/ocr"):
        try:
            req = urllib.request.Request(
                f"{host}{path}", data=payload, headers=headers,
            )
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read()).get("text", "")
        except Exception as exc:
            log.warning("agent %s%s failed: %s", host, path, exc)
            if "timed out" in str(exc):
                break
            continue
    log.warning("agent inference failed at %s", host)
    return None
