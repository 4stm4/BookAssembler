"""Text generation, GPU first (RFC 0022 §4.4, §7.2).

`refine` and `translate` are the two heaviest stages of the pipeline and until
v1.2.0 neither could reach the GPU: `/infer` required an image, so both ran on
the rpi5 CPU while the card idled between pages. One measured run shows the
cost — "LLM time budget exhausted (357s), skipping 83 blocks".

Order here is GPU, then edge cluster. The fallback is not a nicety: bulk work
has its own slice of the weekly quota (§7.2), and when it runs out the Manager
answers 429 by design. Translation continuing slowly on ARM is the intended
outcome of that; failing outright is not.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

from src.agents.router import call_infer, pick
from src.agents.tasks import Priority

log = logging.getLogger(__name__)

#: Edge-cluster ollama, used when the GPU declines or is unreachable.
EDGE_URL = os.environ.get("LLM_AGENT_URL", "http://192.168.88.199:11434")
EDGE_MODEL = os.environ.get("LLM_AGENT_MODEL", "qwen2.5:7b")
EDGE_TIMEOUT = int(os.environ.get("LLM_AGENT_TIMEOUT", "120"))


def _edge_generate(prompt: str, host: Optional[str] = None,
                   model: Optional[str] = None) -> Optional[str]:
    """Generate on the edge cluster's ollama."""
    payload = json.dumps({
        "model": model or EDGE_MODEL,
        "prompt": prompt,
        "stream": False,
        # RFC 0012 §3.1: deterministic LLM calls.
        "options": {"temperature": 0.0, "seed": 42, "num_predict": 256},
        "keep_alive": "10m",
    }).encode()
    req = urllib.request.Request(
        f"{host or EDGE_URL}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=EDGE_TIMEOUT) as resp:
            return json.loads(resp.read()).get("response", "")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        log.warning("edge LLM call failed: %s", e)
        return None


def generate_text(prompt: str, task: str = "refine",
                  host: Optional[str] = None,
                  model: Optional[str] = None,
                  timeout: Optional[int] = None) -> Optional[str]:
    """Answer `prompt`, preferring the GPU agent.

    `host` forces the edge cluster — the caller already knows where it wants to
    go, so no discovery happens and no GPU slot is taken.
    """
    if host is None:
        agent_host, agent_model, kind = pick(task)
        if agent_host:
            text = call_infer(agent_host, task, prompt=prompt, kind=kind,
                              model=model or agent_model,
                              timeout=timeout,
                              priority=int(Priority.BULK))
            if text:
                return text
            # None covers a refusal (429 over the bulk budget), a dead tunnel
            # and a timeout alike. All three mean the same thing to us: this
            # work has to happen somewhere else.
            log.info("GPU declined %s; falling back to the edge cluster", task)
    return _edge_generate(prompt, host=host, model=model)
