"""llm_refinement: The analyzer itself: orchestration and KRM writes."""

import json
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

from src.analyzers.llm_refinement.config import CONFIDENCE_THRESHOLD, MAX_TOTAL_TIME, OLLAMA_MODEL, OLLAMA_URL
from src.analyzers.llm_refinement.prompts import CLASSIFICATION_PROMPT
from src.analyzers.llm_refinement.signals import BATCH_SIZE, VALID_TYPES, logger
from src.analyzers.llm_refinement.rules import _call_ollama, _get_text, _parse_llm_response

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
                # Idempotency marker (RFC 0014). Deliberately a constant, not a
                # timestamp: it lands in the KRM, and a wall clock there would
                # make two runs of the same source differ byte-for-byte,
                # breaking RFC 0009 §5.2.
                block.metadata["llm_refined"] = True
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
                md = child.metadata or {}
                # "llm_refined_at" is the legacy timestamp marker — still
                # honoured so documents persisted before the switch stay skipped.
                if md.get("llm_refined") or md.get("llm_refined_at"):
                    continue
                if child.classification_confidence < CONFIDENCE_THRESHOLD:
                    text = _get_text(child)
                    if text.strip():
                        results.append((child, text))
