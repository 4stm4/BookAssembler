"""llm_refinement: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.llm_refinement.signals import BATCH_SIZE, REQUEST_TIMEOUT, VALID_TYPES, logger
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

from src.analyzers.llm_refinement.config import OLLAMA_MODEL, OLLAMA_URL

def _get_text(block: ParagraphBlock) -> str:
    parts = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)

def _call_ollama(prompt: str, host: Optional[str] = None, model: Optional[str] = None) -> Optional[str]:
    url = f"{host or OLLAMA_URL}/api/generate"
    payload = json.dumps({
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        # RFC 0012 §3.1: deterministic LLM calls (temperature=0, fixed seed).
        "options": {"temperature": 0.0, "seed": 42, "num_predict": 256},
        "keep_alive": "10m",
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        t0 = time.time()
        logger.info("Sending LLM request (%d chars prompt)...", len(prompt))
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())
            elapsed = time.time() - t0
            logger.info("LLM responded in %.1fs", elapsed)
            return data.get("response", "")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        logger.warning("LLM agent call failed: %s", e)
        return None

def _parse_llm_response(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        results = json.loads(match.group())
        if isinstance(results, list):
            return results
    except json.JSONDecodeError:
        pass
    return []
