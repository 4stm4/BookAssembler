"""
LLMRefinementAnalyzer — refines low-confidence blocks using a local LLM.

Connects to ollama (qwen2.5) on OrangePi. Sequential batch processing
with total time budget to avoid blocking the pipeline too long.

Env vars:
- LLM_AGENT_URL: ollama API base (default: http://192.168.88.199:11434)
- LLM_AGENT_MODEL: model name (default: qwen2.5:7b)
- LLM_CONFIDENCE_THRESHOLD: process blocks below this (default: 0.60)
- LLM_MAX_TOTAL_TIME: max seconds for all LLM calls (default: 300)
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import urllib.request
import urllib.error

from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
)

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("LLM_AGENT_URL", "http://192.168.88.199:11434")
OLLAMA_MODEL = os.environ.get("LLM_AGENT_MODEL", "qwen2.5:7b")
CONFIDENCE_THRESHOLD = float(os.environ.get("LLM_CONFIDENCE_THRESHOLD", "0.60"))
BATCH_SIZE = 3
REQUEST_TIMEOUT = 300
MAX_TOTAL_TIME = int(os.environ.get("LLM_MAX_TOTAL_TIME", "300"))

VALID_TYPES = {
    "paragraph", "table_cell", "caption", "toc_entry",
    "code", "heading", "formula", "list_item", "unknown",
}

CLASSIFICATION_PROMPT = """You are a document structure classifier. For each text block, determine its structural type.

Types:
- paragraph: narrative text, multiple sentences
- table_cell: short data from a table (numbers, labels, values)
- caption: figure/table caption ("Figure 1-5 ASCII code")
- toc_entry: table of contents entry ("Chapter Title 42")
- code: source code or assembly listing
- heading: section/chapter title
- formula: mathematical expression
- list_item: item from a numbered/bulleted list

Respond with ONLY a JSON array. Each element: {"id": N, "type": "...", "confidence": 0.0-1.0}

Blocks:
"""


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


class LLMRefinementAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="LLMRefinementAnalyzer",
                version="1.1.0",
                description="Refines low-confidence blocks using local LLM (ollama)",
                krm_permissions={KRMPermission.READ, KRMPermission.TRANSFORM_NODE},
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["BlockClassifierAnalyzer"],
            )
        )
        self._available: Optional[bool] = None

    def _check_availability(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m["name"] for m in data.get("models", [])]
                self._available = OLLAMA_MODEL in models
                if self._available:
                    logger.info("LLM agent: %s on %s", OLLAMA_MODEL, OLLAMA_URL)
                else:
                    logger.warning("Model %s not in %s", OLLAMA_MODEL, models)
        except Exception as e:
            logger.info("LLM agent unavailable (%s): %s", OLLAMA_URL, e)
            self._available = False
        return self._available

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._check_availability():
            return

        low_conf: List[Tuple[ParagraphBlock, str]] = []
        for container in doc.root_containers:
            self._collect_low_confidence(container, low_conf)

        if not low_conf:
            logger.info("No low-confidence blocks to refine")
            return

        logger.info("Refining %d low-confidence blocks via LLM", len(low_conf))

        t_start = time.time()
        refined = 0
        skipped = 0

        for batch_start in range(0, len(low_conf), BATCH_SIZE):
            elapsed = time.time() - t_start
            if elapsed > MAX_TOTAL_TIME:
                remaining = len(low_conf) - batch_start
                logger.info("LLM time budget exhausted (%.0fs), skipping %d blocks", elapsed, remaining)
                skipped += remaining
                break

            batch = low_conf[batch_start:batch_start + BATCH_SIZE]
            prompt = CLASSIFICATION_PROMPT
            for i, (block, text) in enumerate(batch):
                snippet = text[:100] + "..." if len(text) > 100 else text
                prompt += f'{i + 1}. "{snippet}"\n'

            response = _call_ollama(prompt)
            if not response:
                skipped += len(batch)
                continue

            results = _parse_llm_response(response)
            for item in results:
                idx = item.get("id")
                block_type = item.get("type", "")
                confidence = item.get("confidence", 0.5)

                if not isinstance(idx, int) or idx < 1 or idx > len(batch):
                    continue
                if block_type not in VALID_TYPES:
                    continue

                block = batch[idx - 1][0]
                llm_conf = max(0.3, min(0.90, float(confidence)))
                block.classification_confidence = llm_conf
                block.update_confidence()

                if not block.metadata:
                    block.metadata = {}
                block.metadata["llm_suggested_type"] = block_type
                block.metadata["llm_model"] = OLLAMA_MODEL
                refined += 1

        total_time = time.time() - t_start
        logger.info("LLM refinement done: %d refined, %d skipped in %.1fs", refined, skipped, total_time)

    def _collect_low_confidence(
        self,
        container: ContainerUnit,
        results: List[Tuple[ParagraphBlock, str]],
    ) -> None:
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._collect_low_confidence(child, results)
            elif isinstance(child, ParagraphBlock):
                if child.classification_confidence < CONFIDENCE_THRESHOLD:
                    text = _get_text(child)
                    if text.strip():
                        results.append((child, text))
