"""vision_fallback: The analyzer itself: orchestration and KRM writes."""

import time
from typing import Any, Dict, List, Optional, Tuple
from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KRMPermission,
)
from src.agents.manager.router import AgentRouter, vision_generate
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    FormulaBlock,
    KnowledgeDocument,
    ParagraphBlock,
)

from src.analyzers.vision_fallback.config import MAX_VISION_CALLS, MAX_VISION_TIME, VISION_CONFIDENCE_THRESHOLD
from src.analyzers.vision_fallback.prompts import CLASSIFY_PROMPT, FORMULA_PROMPT
from src.analyzers.vision_fallback.signals import log
from src.analyzers.vision_fallback.rules import _page_crop_b64, _parse_classify_response

class VisionFallbackAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="VisionFallbackAnalyzer",
                version="1.0.0",
                description="Vision model fallback for low-confidence blocks and formula OCR",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.MUTATE_ATTRIBUTES,
                },
                rg_permissions=set(),
                kg_permissions=set(),
                depends_on=["LLMRefinementAnalyzer"],
            )
        )
        self._router: Optional[AgentRouter] = None

    def _ensure_router(self) -> Optional[AgentRouter]:
        if self._router is not None:
            return self._router if self._router.vision_available else None
        self._router = AgentRouter()
        if self._router.discover_vision():
            log.info("Vision fallback: model available")
            return self._router
        log.info("Vision fallback: no vision model found, skipping")
        return None

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        router = self._ensure_router()
        if router is None:
            return

        endpoint = router.route("vision")
        if not endpoint:
            return
        host = endpoint["host"]
        model = endpoint["model"]
        kind = endpoint.get("kind", "ollama")

        formulas: List[FormulaBlock] = []
        low_conf: List[ParagraphBlock] = []
        self._collect_targets(doc.root_containers, formulas, low_conf)

        total = len(formulas) + len(low_conf)
        if total == 0:
            return

        log.info(
            "Vision fallback: %d formulas needing OCR, %d low-confidence blocks",
            len(formulas), len(low_conf),
        )

        calls = 0
        t_start = time.time()

        for formula in formulas:
            if calls >= MAX_VISION_CALLS or time.time() - t_start > MAX_VISION_TIME:
                break
            crop = _page_crop_b64(doc, formula)
            if not crop:
                continue
            result = vision_generate(host, model, FORMULA_PROMPT, crop, timeout=60, kind=kind)
            if result and result.strip():
                latex = result.strip()
                if latex.startswith("$"):
                    latex = latex.strip("$")
                if latex.startswith("\\["):
                    latex = latex[2:]
                if latex.endswith("\\]"):
                    latex = latex[:-2]
                formula.latex_expression = latex.strip()
                formula.metadata = formula.metadata or {}
                formula.metadata["vision_ocr"] = True
                formula.metadata["vision_model"] = model
                formula.metadata.pop("needs_vision_ocr", None)
                formula.classification_confidence = max(
                    formula.classification_confidence, 0.80
                )
                formula.update_confidence()
            calls += 1

        for block in low_conf:
            if calls >= MAX_VISION_CALLS or time.time() - t_start > MAX_VISION_TIME:
                break
            crop = _page_crop_b64(doc, block)
            if not crop:
                continue
            result = vision_generate(host, model, CLASSIFY_PROMPT, crop, timeout=30, kind=kind)
            block_type, conf = _parse_classify_response(result)
            if block_type:
                block.metadata = block.metadata or {}
                block.metadata["vision_suggested_type"] = block_type
                block.metadata["vision_confidence"] = conf
                block.metadata["vision_model"] = model
                fused = max(block.classification_confidence, conf * 0.85)
                block.classification_confidence = fused
                block.update_confidence()
            calls += 1

        elapsed = time.time() - t_start
        log.info("Vision fallback done: %d calls in %.1fs", calls, elapsed)

    def _collect_targets(
        self,
        containers: list,
        formulas: List[FormulaBlock],
        low_conf: List[ParagraphBlock],
    ) -> None:
        for node in containers:
            if isinstance(node, ContainerUnit):
                for child in node.children:
                    if isinstance(child, FormulaBlock):
                        if (child.metadata or {}).get("needs_vision_ocr"):
                            formulas.append(child)
                    elif isinstance(child, ParagraphBlock):
                        if child.classification_confidence < VISION_CONFIDENCE_THRESHOLD:
                            if not child.is_tombstoned:
                                low_conf.append(child)
                    elif isinstance(child, ContainerUnit):
                        self._collect_targets([child], formulas, low_conf)
