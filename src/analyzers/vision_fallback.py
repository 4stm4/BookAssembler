"""
VisionFallbackAnalyzer — sends low-confidence and needs_vision_ocr blocks
to a vision model for reclassification or LaTeX extraction.

Runs after LLMRefinement. Uses AgentRouter to discover vision-capable
ollama hosts. Gracefully degrades to no-op when no vision model is available.

For FormulaBlock with needs_vision_ocr: extracts LaTeX via vision model.
For low-confidence ParagraphBlock: reclassifies via vision prompt.
"""

import base64
import logging
import os
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

log = logging.getLogger(__name__)

VISION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("KAE_VISION_CONFIDENCE_THRESHOLD", "0.45")
)
MAX_VISION_CALLS = int(os.environ.get("KAE_VISION_MAX_CALLS", "20"))
MAX_VISION_TIME = int(os.environ.get("KAE_VISION_MAX_TIME", "300"))

CLASSIFY_PROMPT = (
    "Look at this cropped region from a scanned document page. "
    "What type of content is shown? Answer with exactly ONE word from this list: "
    "paragraph, table, formula, figure, code, caption, heading, list, footnote, "
    "bibliography, algorithm, index, toc, blank. "
    "Then on a new line, give a confidence score 0.0-1.0."
)

FORMULA_PROMPT = (
    "This image contains a mathematical formula from a technical document. "
    "Extract the formula and write it as valid LaTeX code. "
    "Output ONLY the LaTeX expression, nothing else. "
    "Do not wrap in $ or \\begin{equation}."
)

_TYPE_MAP = {
    "paragraph": "paragraph",
    "table": "table",
    "formula": "formula",
    "figure": "figure",
    "code": "code",
    "caption": "caption",
    "heading": "heading",
    "list": "list",
    "footnote": "footnote",
    "bibliography": "bibliography",
    "algorithm": "algorithm",
    "index": "index",
    "toc": "toc_entry",
    "blank": "blank",
}


def _get_text(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)


def _page_crop_b64(doc: KnowledgeDocument, block: Any) -> Optional[str]:
    """Get base64-encoded crop of the block's region from the source PDF.

    Returns None if the source is not available or pymupdf is not installed.
    This is best-effort — the analyzer works without crops by using text prompts.
    """
    vl = getattr(block, "visual_layout", None)
    if not vl:
        return None
    bb = getattr(vl, "bounding_box", None)
    page_idx = getattr(vl, "page_or_screen_index", None)
    if bb is None or page_idx is None:
        return None

    source = doc.source_uri or ""
    if not source or not os.path.isfile(source):
        return None

    try:
        import fitz  # type: ignore[import-untyped]
        pdf = fitz.open(source)
        if page_idx >= len(pdf):
            pdf.close()
            return None
        page = pdf[page_idx]
        pw, ph = page.rect.width, page.rect.height
        margin = 0.02
        clip = fitz.Rect(
            max(0, bb.x0 - margin) * pw,
            max(0, bb.y0 - margin) * ph,
            min(1, bb.x1 + margin) * pw,
            min(1, bb.y1 + margin) * ph,
        )
        pix = page.get_pixmap(clip=clip, dpi=150)
        img_bytes = pix.tobytes("png")
        pdf.close()
        return base64.b64encode(img_bytes).decode()
    except Exception as e:
        log.debug("Could not crop page region: %s", e)
        return None


def _parse_classify_response(text: Optional[str]) -> Tuple[Optional[str], float]:
    if not text:
        return None, 0.0
    lines = text.strip().split("\n")
    block_type = lines[0].strip().lower().rstrip(".")
    mapped = _TYPE_MAP.get(block_type)
    confidence = 0.7
    if len(lines) > 1:
        try:
            confidence = float(lines[1].strip())
            confidence = max(0.3, min(0.95, confidence))
        except ValueError:
            pass
    return mapped, confidence


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
