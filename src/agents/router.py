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
import socket
import time
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


INFER_TIMEOUT = 45      # rpi5 uploads ~15KB through the tunnel at ~1.3 KB/s
# Hosts that answered "I don't understand a source reference". Probing once per
# host keeps a runner without the feature from paying a failed request per page.
_NO_SOURCE_FETCH: set = set()
INFER_ATTEMPTS = 3
INFER_BACKOFF = 2.0     # seconds, linear — an instant retry hits the same jam


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, socket.timeout) or "timed out" in str(exc)


def _post_infer(
    url: str, payload: bytes, headers: dict,
) -> Tuple[Optional[str], Optional[Exception]]:
    """POST to one inference endpoint, retrying only on read timeout.

    Returns (text, None) on success or (None, last_exception) on failure, so the
    caller can tell a saturated link apart from a wrong endpoint.
    """
    last: Optional[Exception] = None
    for attempt in range(INFER_ATTEMPTS):
        try:
            req = urllib.request.Request(url, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=INFER_TIMEOUT) as r:
                return json.loads(r.read()).get("text", ""), None
        except Exception as exc:
            last = exc
            log.warning("agent %s attempt %d/%d: %s",
                        url, attempt + 1, INFER_ATTEMPTS, exc)
            if not _is_timeout(exc):
                break
            if attempt + 1 < INFER_ATTEMPTS:
                time.sleep(INFER_BACKOFF * (attempt + 1))
    return None, last


def supports_source_fetch(host: str) -> bool:
    """True if this agent is configured to fetch the source itself, and has not
    already refused a reference request.

    Measured on this deployment: rpi5 uploads at ~1.7 KB/s but downloads at
    ~4.6 MB/s, so pushing a rendered page costs ~13s while the inference costs
    1-3s. An agent that fetches the document itself turns a 22KB upload into a
    ~200 byte one and moves the bytes over the runner's own link instead.
    """
    if host in _NO_SOURCE_FETCH:
        return False
    for a in load_agents():
        if a.get("host", "").rstrip("/") == host.rstrip("/"):
            return bool(a.get("source_fetch"))
    return False


def _call_by_reference(
    host: str, task: str, source_url: str, page: int, prompt: Optional[str],
) -> Optional[str]:
    """Ask the agent to fetch and render the page itself.

    A few hundred bytes leave rpi5 instead of a rendered image, and the document
    travels over the runner's link. Returns None when the agent cannot do this,
    and remembers that so the rest of the book skips straight to the image path.
    """
    body = {"source_url": source_url, "page": page, "task": task}
    if prompt:
        body["prompt"] = prompt
    headers: dict = {"Content-Type": "application/json"}
    token = _token_for_host(host)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    text, exc = _post_infer(
        f"{host}/infer", json.dumps(body).encode(), headers,
    )
    if text is not None:
        return text
    if exc is not None and not _is_timeout(exc):
        # A 4xx/5xx here means the runner does not understand a reference
        # request; a timeout means the link, and that would say nothing about
        # the feature.
        log.info("agent %s does not accept source references (%s) — "
                 "falling back to uploading images", host, exc)
        _NO_SOURCE_FETCH.add(host)
    return None


def call_infer(
    host: str, task: str, image_png: Optional[bytes] = None,
    prompt: Optional[str] = None, kind: str = "multimodel",
    model: Optional[str] = None,
    source_url: Optional[str] = None, page: Optional[int] = None,
) -> Optional[str]:
    """Run inference on one page.

    Prefers sending a reference (source_url + page) so the agent fetches and
    renders the page on its own side; falls back to uploading the rendered image
    when the agent has no such support. Supports multimodel, got-ocr and ollama.
    """
    if (source_url and page is not None and kind != "ollama"
            and supports_source_fetch(host)):
        text = _call_by_reference(host, task, source_url, page, prompt)
        if text is not None:
            return text
        # The agent could not use the reference; fall through to the image so a
        # page is still analysed rather than lost.
        if image_png is None:
            return None

    if image_png is None:
        return None
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
        text, exc = _post_infer(f"{host}{path}", payload, headers)
        if text is not None:
            return text
        # A timeout means the uplink is saturated, not that the endpoint is
        # wrong — trying the other path would just queue more bytes behind it.
        # Any other failure (e.g. 404 on /infer from a got-ocr agent) is worth
        # retrying on the next path.
        if exc is not None and _is_timeout(exc):
            break
    log.warning("agent inference failed at %s", host)
    return None
