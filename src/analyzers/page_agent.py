"""
PageAgentAnalyzer — pipeline stage that pulls a vision agent into extraction.

For pages that look like tables (dense grid of short numeric blocks that
TableDetector didn't cluster), the analyzer renders the region, sends it to the
first reachable agent with role "table" (see src/agents.router), and stores the
returned LaTeX on a new TableBlock. Absorbed source blocks are tombstoned
(RFC 0001 §2.4).

Runs after TableDetectorAnalyzer: if there's already a spatial TableBlock on the
page, we skip it — the extractor did its job. If not, but heuristics say
"table-like", we ask the agent.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from src.agents import call_infer, pick
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TextLineInline,
    StyledTextSpan,
    VisualLayout,
)

log = logging.getLogger(__name__)

MIN_NUMERIC_RATIO = 0.35  # numeric density hint (real tables have ≥35% numeric)
MIN_BLOCKS = 5            # need enough blocks to look like a grid
MIN_SHORT_RATIO = 0.7     # most blocks are short (labels/cells, not paragraphs)


def _text(node: Any) -> str:
    if isinstance(node, ParagraphBlock):
        return " ".join(
            s.text for i in (node.inlines or [])
            for s in getattr(i, "spans", []) if hasattr(s, "text")
        ).strip()
    return (getattr(node, "title", "") or "").strip()


def _looks_numeric(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 40:
        return False
    digits = sum(c.isdigit() for c in t)
    return digits >= 1 and digits / max(1, len(t)) >= 0.3


class PageAgentAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="PageAgentAnalyzer",
                version="1.0.0",
                description="Uses a vision agent to recognize table pages missed by TableDetector",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
                    KRMPermission.MUTATE_ATTRIBUTES,
                },
                depends_on=["TableDetectorAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Only worth calling if a `table`-role agent is reachable.
        host, _model, _kind = pick("table")
        if not host:
            log.info("PageAgent: no table-role agent — skipping")
            return

        # Group non-tombstoned leaf blocks by page.
        pages: Dict[int, List[Tuple[Any, ContainerUnit]]] = {}
        table_pages: Set[int] = set()

        def walk(node: Any, parent: Optional[ContainerUnit]) -> None:
            if getattr(node, "is_tombstoned", False):
                return
            vl = getattr(node, "visual_layout", None)
            pg = getattr(vl, "page_or_screen_index", None) if vl else None
            if isinstance(node, TableBlock) and pg is not None:
                table_pages.add(pg)
            if isinstance(node, ContainerUnit):
                for ch in node.children:
                    walk(ch, node)
            elif pg is not None and parent is not None and _text(node):
                pages.setdefault(pg, []).append((node, parent))

        for c in doc.root_containers:
            walk(c, None)

        pdf_path = _resolve_source_path(doc)
        if not pdf_path:
            log.info("PageAgent: cannot resolve source PDF — skipping")
            return

        for pg, blocks in sorted(pages.items()):
            if pg in table_pages:
                continue  # TableDetector already got it
            if len(blocks) < MIN_BLOCKS:
                continue
            texts = [_text(b) for b, _ in blocks]
            joined = " ".join(texts).lower()
            numeric = sum(1 for t in texts if _looks_numeric(t))
            short = sum(1 for t in texts if len(t) <= 40)
            # Explicit table-title on page: "Table N", "Figure/Table 1", "Analysis of"
            titled = ("table " in joined or " analysis of" in joined
                      or " cost of " in joined or "monthly use" in joined)
            looks_table = (
                titled
                or numeric / len(blocks) >= MIN_NUMERIC_RATIO
                or short / len(blocks) >= MIN_SHORT_RATIO
            )
            if not looks_table:
                continue

            log.info("PageAgent: page %d looks like a table "
                     "(titled=%s, %d/%d numeric, %d/%d short)",
                     pg, titled, numeric, len(blocks), short, len(blocks))
            latex = self._recognize_table(pdf_path, pg, host, blocks)
            if not latex:
                continue
            self._replace_with_table(blocks, latex, pg)

    def _recognize_table(
        self, pdf_path: str, page_index: int, host: str,
        blocks: List[Tuple[Any, ContainerUnit]],
    ) -> Optional[str]:
        """Render the page region covering these blocks and send to the agent."""
        import pymupdf as fitz

        bbs = [b.visual_layout.bounding_box for b, _ in blocks if getattr(b, "visual_layout", None)]
        if not bbs:
            return None
        x0 = max(0.0, min(b.x0 for b in bbs) - 0.02)
        y0 = max(0.0, min(b.y0 for b in bbs) - 0.02)
        x1 = min(1.0, max(b.x1 for b in bbs) + 0.02)
        y1 = min(1.0, max(b.y1 for b in bbs) + 0.02)

        pdf = fitz.open(pdf_path)
        try:
            page = pdf[page_index]
            pw, ph = page.rect.width, page.rect.height
            clip = fitz.Rect(x0 * pw, y0 * ph, x1 * pw, y1 * ph)
            # 100dpi is enough for vision-LLMs; 150+ triggers OOM on T4.
            png = page.get_pixmap(clip=clip, dpi=100).tobytes("png")
        finally:
            pdf.close()

        latex = call_infer(host, "table", png)
        if not latex or "tabular" not in latex.lower():
            return None
        # Strip markdown fences the LLM often wraps around code.
        s = latex.strip()
        if s.startswith("```"):
            s = s.split("\n", 1)[1] if "\n" in s else s[3:]
            if s.rstrip().endswith("```"):
                s = s.rstrip()[:-3].rstrip()
        return s

    def _replace_with_table(
        self, blocks: List[Tuple[Any, ContainerUnit]], latex: str, page_index: int,
    ) -> None:
        """Insert a TableBlock carrying the recognized LaTeX; tombstone the sources."""
        parent = blocks[0][1]
        try:
            first_idx = parent.children.index(blocks[0][0])
        except ValueError:
            first_idx = 0

        # Empty spatial grid: the LaTeX in metadata is what latex_builder uses.
        table = TableBlock(grid=[[TableCell(content=[])]])
        table.visual_layout = VisualLayout(
            bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
            page_or_screen_index=page_index,
        )
        table.metadata = {"latex": latex, "source": "PageAgent"}
        table.extraction_confidence = 0.95
        table.classification_confidence = 0.95
        table.confidence_score = 0.95
        parent.children.insert(min(first_idx, len(parent.children)), table)

        for block, _ in blocks:
            block.is_tombstoned = True
            if not block.metadata:
                block.metadata = {}
            block.metadata["tombstone_reason"] = f"merged_into_table_agent:{table.id}"


def _resolve_source_path(doc: KnowledgeDocument) -> Optional[str]:
    """Best-effort: resolve doc.source_uri to a local PDF file the agent can read."""
    uri = doc.source_uri or ""
    if uri.startswith("sep://"):
        try:
            _, rel = uri.replace("sep://", "").split("/", 1)
        except ValueError:
            return None
        root = os.environ.get("KAE_SSD_PATH", "/data/kae")
        cand = os.path.join(root, rel)
        return cand if os.path.exists(cand) else None
    if uri.startswith("file://"):
        p = uri[len("file://") :]
        return p if os.path.exists(p) else None
    return None
