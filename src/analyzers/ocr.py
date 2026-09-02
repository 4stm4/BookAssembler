"""
OCRAnalyzer — recovers text from pages that have no text layer (RFC 0008 §75).

PdfSourceAdapter marks such pages `needs_ocr=True` and emits an empty
placeholder for each, because there is nothing to extract. Until this analyzer
existed the flag was written and never read: on the corpus in /data/kae/books
that is 238 of 1738 pages, and 19 documents that are scans end to end, which
came out of the pipeline as empty placeholders and nothing else.

This is also the one case where a vision agent is not an optimisation but the
only option — there is no text layer to fall back on, and OCR on the ARM hosts
of this cluster runs in minutes per page.

The placeholder is tombstoned rather than dropped (RFC 0001 §2.4) and the
recovered lines are inserted in its place, each carrying the page's geometry so
the assembler can still lay the page out (RFC 0021 §5.4).
"""

import logging
import os
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
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)

log = logging.getLogger(__name__)

# Same reasoning as PageAgent: the cost is generation, not transfer.
OCR_CONCURRENCY = int(os.environ.get("KAE_OCR_CONCURRENCY", "2"))
# A scanned page is mostly text, so it needs more resolution than a page we
# only classify — but the ceiling is still what the model answers on in time.
OCR_DPI = int(os.environ.get("KAE_OCR_DPI", "110"))
OCR_MAX_DIM = int(os.environ.get("KAE_OCR_MAX_DIM", "900"))
FAILURE_BUDGET_RATIO = 0.5
MIN_FAILURE_BUDGET = 3

_PROMPT = (
    "This is a scanned page with no text layer. Transcribe all readable text, "
    "preserving line breaks and reading order. Do not describe the page, do "
    "not add commentary — output the text only. If the page has no readable "
    "text, output nothing."
)


def _needs_ocr(node: Any) -> bool:
    return bool((getattr(node, "metadata", None) or {}).get("needs_ocr"))


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
        pages = [_page_of(node) for node, _ in targets]
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
                          kind=kind, model=model) or ""

    def _replace(
        self, node: Any, parent: ContainerUnit, text: str, source_uri: str,
    ) -> None:
        """Tombstone the placeholder and insert the recovered lines in its place."""
        page = _page_of(node)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return

        try:
            at = parent.children.index(node)
        except ValueError:
            at = len(parent.children)

        # The page's own box: OCR gives reading order, not per-line geometry,
        # so every line shares the page region rather than claiming a false one.
        vl = getattr(node, "visual_layout", None)
        bbox = getattr(vl, "bounding_box", None) or NormalizedRect(0.0, 0.0, 1.0, 1.0)

        made = []
        for i, line in enumerate(lines):
            block = ParagraphBlock(
                id=derive_source_id("ocr-line", source_uri, page, bbox, line, i),
                inlines=[TextLineInline(spans=[StyledTextSpan(text=line)])],
                parent_container_id=parent.id,
                provenance_info=getattr(node, "provenance_info", None),
                visual_layout=VisualLayout(
                    bounding_box=bbox, page_or_screen_index=page or 0,
                ),
                extraction_confidence=0.6,       # OCR, not an extracted layer
                classification_confidence=0.5,
                confidence_score=0.5,
            )
            block.metadata = {"ocr_source": "vision-agent"}
            made.append(block)

        parent.children[at:at] = made
        node.is_tombstoned = True
        if not node.metadata:
            node.metadata = {}
        node.metadata["tombstone_reason"] = "replaced_by_ocr"
        node.metadata.pop("needs_ocr", None)


def _page_of(node: Any) -> Optional[int]:
    vl = getattr(node, "visual_layout", None)
    return getattr(vl, "page_or_screen_index", None) if vl else None


def _resolve_source_path(doc: KnowledgeDocument) -> Optional[str]:
    from src.analyzers.page_agent import _resolve_source_path as resolve
    return resolve(doc)
