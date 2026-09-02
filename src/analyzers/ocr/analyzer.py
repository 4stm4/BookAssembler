"""ocr: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import page_of
from typing import Any, Dict, List, Optional, Tuple
from src.agents import call_infer, pick
from src.analyzers._agent_batch import run_bounded
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_source_id
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyleDescriptor,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)

from src.analyzers.ocr.config import OCR_ATTEMPTS, OCR_CONCURRENCY, OCR_DPI, OCR_MAX_DIM, OCR_TIMEOUT
from src.analyzers.ocr.prompts import _PROMPT
from src.analyzers.ocr.signals import FAILURE_BUDGET_RATIO, MIN_FAILURE_BUDGET, log
from src.analyzers.ocr.rules import _needs_ocr, _parse_ocr, _resolve_source_path

class OCRAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="OCRAnalyzer",
                version="1.0.0",
                description=(
                    "Recovers text from pages with no text layer via a vision "
                    "agent (RFC 0008 §75)"
                ),
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
                },
                depends_on=["NormalizationAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        targets: List[Tuple[Any, ContainerUnit]] = []

        def walk(node: Any, parent: Optional[ContainerUnit]) -> None:
            if getattr(node, "is_tombstoned", False):
                return
            if isinstance(node, ContainerUnit):
                for ch in list(node.children):
                    walk(ch, node)
            elif parent is not None and _needs_ocr(node):
                targets.append((node, parent))

        for c in doc.root_containers:
            walk(c, None)

        if not targets:
            return

        host, model, kind = pick("vision")
        if not host:
            # Nothing to fall back on: without a text layer there is no text.
            log.info("OCRAnalyzer: %d page(s) need OCR but no vision agent — "
                     "leaving them flagged", len(targets))
            return

        pdf_path = _resolve_source_path(doc)
        if not pdf_path:
            log.info("OCRAnalyzer: cannot resolve source PDF — skipping")
            return

        texts = self._fetch(targets, pdf_path, host, kind, model)

        # Applied in page order, never in completion order (RFC 0009 §5.2).
        recovered = 0
        for node, parent in targets:
            text = texts.get(id(node))
            if not text:
                continue
            self._replace(node, parent, text, doc.source_uri or "")
            recovered += 1
        log.info("OCRAnalyzer: recovered text on %d/%d page(s)",
                 recovered, len(targets))

    def _fetch(
        self, targets: List[Tuple[Any, ContainerUnit]], pdf_path: str,
        host: str, kind: str, model: Optional[str],
    ) -> Dict[int, str]:
        pages = [page_of(node) for node, _ in targets]
        budget = max(MIN_FAILURE_BUDGET, int(len(targets) * FAILURE_BUDGET_RATIO))
        by_index, _failures = run_bounded(
            pages,
            lambda pg: self._ocr_page(pdf_path, pg, host, kind, model),
            concurrency=OCR_CONCURRENCY, budget=budget, label="OCRAnalyzer",
        )
        return {
            id(node): (by_index.get(i) or "")
            for i, (node, _) in enumerate(targets)
        }

    def _ocr_page(
        self, pdf_path: str, page_index: Optional[int],
        host: str, kind: str, model: Optional[str],
    ) -> str:
        if page_index is None:
            return ""
        import pymupdf as fitz
        from src.analyzers.page_agent import _pixmap_to_jpeg

        pdf = fitz.open(pdf_path)
        try:
            png = _pixmap_to_jpeg(
                pdf[page_index].get_pixmap(dpi=OCR_DPI),
                max_dim=OCR_MAX_DIM,
            )
        finally:
            pdf.close()
        return call_infer(host, "vision", png, prompt=_PROMPT,
                          kind=kind, model=model,
                          timeout=OCR_TIMEOUT, attempts=OCR_ATTEMPTS) or ""

    def _replace(
        self, node: Any, parent: ContainerUnit, text: str, source_uri: str,
    ) -> None:
        """Tombstone the placeholder and insert the recovered lines in its place."""
        page = page_of(node)

        # The page's own box. Model boxes are image-relative, so they are
        # mapped into it; a line the model gave no box for falls back to it.
        vl = getattr(node, "visual_layout", None)
        page_box = getattr(vl, "bounding_box", None) or NormalizedRect(0.0, 0.0, 1.0, 1.0)

        lines = _parse_ocr(text, page_box)
        if not lines:
            return

        try:
            at = parent.children.index(node)
        except ValueError:
            at = len(parent.children)

        made = []
        for i, (line, rect, style) in enumerate(lines):
            bbox = rect or page_box
            block = ParagraphBlock(
                id=derive_source_id("ocr-line", source_uri, page, bbox, line, i),
                inlines=[TextLineInline(spans=[StyledTextSpan(text=line)])],
                parent_container_id=parent.id,
                provenance_info=getattr(node, "provenance_info", None),
                visual_layout=VisualLayout(
                    bounding_box=bbox, page_or_screen_index=page or 0,
                    style=style,
                ),
                extraction_confidence=0.6,       # OCR, not an extracted layer
                classification_confidence=0.5,
                confidence_score=0.5,
            )
            block.metadata = {
                "ocr_source": "vision-agent",
                "ocr_geometry": "model" if rect else "page",
            }
            made.append(block)

        parent.children[at:at] = made
        node.is_tombstoned = True
        if not node.metadata:
            node.metadata = {}
        node.metadata["tombstone_reason"] = "replaced_by_ocr"
        node.metadata.pop("needs_ocr", None)
