"""
Vision-capable agent router for KAE (RFC 0022).

Routes vision tasks to ollama instances that have a vision model loaded,
with Kaggle GPU as an opt-in second-tier fallback.

Roles:
- "text": standard LLM inference (qwen2.5, llama, etc.)
- "vision": multimodal inference (llava, llava:7b, etc.)
- "table": table recognition via vision model
"""

import base64
import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

VISION_MODELS = {"llava", "llava:7b", "llava:13b", "llava-llama3", "bakllava"}


def _probe_models(host: str) -> List[str]:
    try:
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def has_vision_model(host: str) -> bool:
    models = _probe_models(host)
    return any(m.split(":")[0] in VISION_MODELS or m in VISION_MODELS for m in models)


def find_vision_host(hosts: Optional[List[str]] = None) -> Optional[str]:
    """Find the first host with a vision model available."""
    if hosts is None:
        default = os.environ.get("KAE_OLLAMA_HOST", "http://localhost:11434")
        hosts = [default]
        extra = os.environ.get("KAE_OLLAMA_VISION_HOST")
        if extra:
            hosts.insert(0, extra)
    for host in hosts:
        if has_vision_model(host.rstrip("/")):
            return host.rstrip("/")
    return None


def vision_generate(
    host: str,
    model: str,
    prompt: str,
    image_b64: str,
    timeout: int = 120,
    kind: str = "ollama",
) -> Optional[str]:
    """Call a vision backend (ollama or multimodel runner) with an image."""
    if kind == "multimodel":
        url = f"{host}/infer"
        payload = json.dumps({
            "image_b64": image_b64,
            "task": "vision",
            "prompt": prompt,
        }).encode()
    else:
        url = f"{host}/api/generate"
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": {"temperature": 0.0, "seed": 42},
        }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            if kind == "multimodel":
                return data.get("text", data.get("response", ""))
            return data.get("response", "")
    except Exception as e:
        log.warning("Vision generate failed on %s: %s", host, e)
        return None


def formula_vision_fallback(
    host: str,
    model: str,
    image_bytes: bytes,
    kind: str = "ollama",
) -> Optional[str]:
    """Use vision model to extract LaTeX from a formula image."""
    b64 = base64.b64encode(image_bytes).decode()
    prompt = (
        "This image contains a mathematical formula. "
        "Extract the formula and write it as valid LaTeX code. "
        "Output ONLY the LaTeX expression, nothing else."
    )
    return vision_generate(host, model, prompt, b64, kind=kind)


class AgentRouter:
    """Routes inference requests to available backends by role."""

    def __init__(self, hosts: Optional[List[str]] = None) -> None:
        self._hosts = hosts or []
        if not self._hosts:
            default = os.environ.get("KAE_OLLAMA_HOST", "http://localhost:11434")
            self._hosts = [default]
            extra = os.environ.get("KAE_OLLAMA_VISION_HOST")
            if extra:
                self._hosts.append(extra)
        self._vision_host: Optional[str] = None
        self._vision_model: Optional[str] = None
        self._kind: str = "ollama"

    def discover_vision(self) -> bool:
        # 1. Check agents.json for a multimodel runner with "vision" role
        agents_path = os.path.join(
            os.environ.get("KAE_SSD_PATH", "/data/kae"), "agents.json"
        )
        if os.path.exists(agents_path):
            try:
                with open(agents_path) as f:
                    agents = json.load(f)
                for a in agents:
                    if "vision" in (a.get("roles") or []) and a.get("kind") == "multimodel":
                        host = a["host"].rstrip("/")
                        try:
                            req = urllib.request.Request(f"{host}/health", method="GET")
                            with urllib.request.urlopen(req, timeout=10) as resp:
                                data = json.loads(resp.read())
                                if data.get("ready"):
                                    self._vision_host = host
                                    self._vision_model = (data.get("models_loaded") or [""])[0]
                                    self._kind = "multimodel"
                                    log.info("Vision agent discovered: %s on %s", self._vision_model, host)
                                    return True
                        except Exception as e:
                            log.debug("Vision agent %s unreachable: %s", host, e)
            except Exception:
                pass

        # 2. Fallback: check ollama hosts for vision models
        for host in self._hosts:
            h = host.rstrip("/")
            models = _probe_models(h)
            for m in models:
                base = m.split(":")[0]
                if base in VISION_MODELS or m in VISION_MODELS:
                    self._vision_host = h
                    self._vision_model = m
                    self._kind = "ollama"
                    log.info("Vision model discovered: %s on %s", m, h)
                    return True
        return False

    @property
    def vision_available(self) -> bool:
        return self._vision_host is not None

    def route(self, role: str) -> Optional[Dict[str, str]]:
        if role == "vision" and self._vision_host and self._vision_model:
            return {"host": self._vision_host, "model": self._vision_model, "kind": self._kind}
        if role in ("text", "table"):
            return {"host": self._hosts[0].rstrip("/"), "model": "", "kind": "ollama"}
        return None
