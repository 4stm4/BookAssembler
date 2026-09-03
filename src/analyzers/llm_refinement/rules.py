"""llm_refinement: Pure decision logic — no KRM writes, no I/O."""

from src.agents.text import generate_text
from src.analyzers.llm_refinement.signals import BATCH_SIZE, REQUEST_TIMEOUT, VALID_TYPES, logger
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
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

def _call_ollama(prompt: str, host: Optional[str] = None,
                 model: Optional[str] = None) -> Optional[str]:
    """Refine a batch of blocks, on the GPU when one will take it.

    Kept under this name because it is the seam the tests patch, but it is no
    longer ollama-only: RFC 0022 v1.2.0 lets task `refine` run on the Runner,
    and the edge cluster is now the fallback rather than the only path.
    """
    t0 = time.time()
    logger.info("Sending LLM request (%d chars prompt)...", len(prompt))
    out = generate_text(prompt, task="refine", host=host, model=model,
                        timeout=REQUEST_TIMEOUT)
    logger.info("LLM responded in %.1fs", time.time() - t0)
    return out


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
