"""page_agent: The analyzer itself: orchestration and KRM writes."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from src.agents import call_infer, pick
from src.analyzers._agent_batch import run_bounded
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.geometry import union_bbox
from src.krm.identity import derive_composite_id
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

from src.analyzers.page_agent.config import RENDER_DPI, VISION_CONCURRENCY
from src.analyzers.page_agent.signals import FAILURE_BUDGET_RATIO, MIN_BLOCKS, MIN_FAILURE_BUDGET, MIN_NUMERIC_RATIO, MIN_SHORT_RATIO, log
from src.analyzers.page_agent.rules import _PageResult, _clean_tabular, _looks_numeric, _pixmap_to_jpeg, _resolve_source_path, _text

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
        # Prefer a `vision`-role agent (classifies the whole page); fall back to
        # `table`-only if that's all that's available.
        host, _model, _kind = pick("vision")
        classify_mode = host is not None
        if not host:
            host, _model, _kind = pick("table")
            if not host:
                log.info("PageAgent: no vision/table agent — skipping")
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
            log.info("PageAgent: cannot resolve source PDF (uri=%r) — skipping",
                     getattr(doc, "source_uri", None))
            return

        candidates = [
            (pg, blocks) for pg, blocks in sorted(pages.items())
            if self._is_candidate(pg, blocks, table_pages, classify_mode)
        ]
        if not candidates:
            return

        results = self._fetch_pages(
            candidates, pdf_path, host, classify_mode, _kind, _model,
        )

        # Mutations run sequentially in page order, never in completion order:
        # applying results as they arrive would make the KRM depend on network
        # timing and break RFC 0009 §5.2.
        for pg, blocks in candidates:
            res = results.get(pg)
            if res is None or res.failed:
                continue
            if res.role:
                self._apply_page_role(blocks, res.role)
            # TableDetector already produced a spatial table here; adding the
            # agent's would leave the page with two tables for one grid.
            if res.table_latex and pg not in table_pages:
                self._replace_with_table(blocks, res.table_latex, pg)
                continue
            if res.types:
                self._apply_types(blocks, res.types)

    def _is_candidate(
        self, pg: int, blocks: List[Tuple[Any, ContainerUnit]],
        table_pages: Set[int], classify_mode: bool,
    ) -> bool:
        if classify_mode:
            # A vision agent classifies the page and every block on it, which is
            # useful on any page with content — including sparse ones and pages
            # where TableDetector already found a table. Those two filters were
            # sized for a serial pipeline and skipped over half the book; with
            # requests overlapping there is no reason to pay them.
            return bool(blocks)
        if pg in table_pages:
            return False
        if len(blocks) < MIN_BLOCKS:
            return False
        # Without a vision agent only the table heuristic is available.
        texts = [_text(b) for b, _ in blocks]
        joined = " ".join(texts).lower()
        numeric = sum(1 for t in texts if _looks_numeric(t))
        short = sum(1 for t in texts if len(t) <= 40)
        titled = ("table " in joined or " analysis of" in joined
                  or " cost of " in joined or "monthly use" in joined)
        return bool(titled
                    or numeric / len(blocks) >= MIN_NUMERIC_RATIO
                    or short / len(blocks) >= MIN_SHORT_RATIO)

    def _fetch_pages(
        self, candidates: List[Tuple[int, List[Tuple[Any, ContainerUnit]]]],
        pdf_path: str, host: str, classify_mode: bool,
        kind: str, model: Optional[str],
    ) -> Dict[int, "_PageResult"]:
        """Query the agent for every candidate page, several requests in flight.

        The agent answers in seconds while a single upload through the tunnel
        takes far longer, so serial requests left the GPU idle for most of the
        run. Pages are independent, so the wait overlaps. This function performs
        no KRM mutation — the caller applies results in page order.
        """
        budget = max(MIN_FAILURE_BUDGET, int(len(candidates) * FAILURE_BUDGET_RATIO))
        started = time.time()
        by_index, failures = run_bounded(
            candidates,
            lambda pair: self._analyze_page(
                pdf_path, pair[0], host, pair[1], classify_mode, kind, model,
            ),
            concurrency=VISION_CONCURRENCY, budget=budget, label="PageAgent",
        )
        results: Dict[int, _PageResult] = {
            pg: by_index.get(i) or _PageResult(failed=True)
            for i, (pg, _) in enumerate(candidates)
        }

        ok = sum(1 for r in results.values() if not r.failed)
        log.info(
            "PageAgent: %d/%d pages in %.0fs (%d in flight, %d failed)",
            ok, len(candidates), time.time() - started, VISION_CONCURRENCY, failures,
        )
        return results

    def _analyze_page(
        self, pdf_path: str, page_index: int, host: str,
        blocks: List[Tuple[Any, ContainerUnit]],
        classify_mode: bool, kind: str, model: Optional[str],
    ) -> "_PageResult":
        """One page's network work. Runs on a worker thread; touches no KRM."""
        if not classify_mode:
            latex = self._recognize_table(
                pdf_path, page_index, host, blocks, kind=kind, model=model,
            )
            return _PageResult(role="", table_latex=latex)

        role, types, latex = self._classify_page(
            pdf_path, page_index, host, blocks, kind=kind, model=model,
        )
        log.info("PageAgent: page %d role=%s, %d block types",
                 page_index, role, len(types))
        if role == "table" and not latex:
            # The page-level answer carried no usable table; fall back to the
            # cropped, higher-fidelity request for this page only.
            latex = self._recognize_table(
                pdf_path, page_index, host, blocks, kind=kind, model=model,
            )
        return _PageResult(role=role, types=types, table_latex=latex)

    def _classify_page(
        self, pdf_path: str, page_index: int, host: str,
        blocks: List[Tuple[Any, ContainerUnit]],
        kind: str = "multimodel", model: Optional[str] = None,
    ) -> Tuple[str, Dict[int, str], Optional[str]]:
        """Ask a vision agent to classify a page and every block on it.

        Returns (page_role, {block_index: type}, table_latex).

        The table LaTeX is requested in the same call: asking for the role first
        and the table afterwards meant two crossings of the tunnel for every
        table page, and the crossing — not the inference — is what costs time.
        """
        import json as _json
        import re as _re
        import pymupdf as fitz

        pdf = fitz.open(pdf_path)
        try:
            page = pdf[page_index]
            png = _pixmap_to_jpeg(page.get_pixmap(dpi=RENDER_DPI))
        finally:
            pdf.close()

        sample = blocks[:15]
        listing = "\n".join(
            f"{i + 1}. \"{_text(b)[:60]}\"" for i, (b, _) in enumerate(sample)
        )
        prompt = (
            "This image is one page of a scanned book. Along with it you get the "
            "text blocks extracted from the page (sample).\n\n"
            f"BLOCKS:\n{listing}\n\n"
            "Decide the PAGE ROLE: title, toc, table, diagram, figure, code, "
            "formula, text. Classify each listed block: paragraph, heading, "
            "toc_entry, caption, code, formula, list_item, table_cell, title, label.\n"
            "If the PAGE ROLE is table, also transcribe it as a LaTeX tabular "
            'in the "table" field; otherwise set "table" to null.\n'
            'Reply JSON only: {"role":"...","blocks":[{"n":1,"type":"..."},...],'
            '"table":"\\\\begin{tabular}...\\\\end{tabular}"}.'
        )
        text = call_infer(
            host, "vision", png, prompt=prompt, kind=kind, model=model,
        ) or ""
        role = "text"
        types: Dict[int, str] = {}
        latex: Optional[str] = None
        m = _re.search(r"\{.*\}", text, _re.DOTALL)
        if m:
            try:
                data = _json.loads(m.group())
                role = str(data.get("role", "text")).lower().strip()
                for item in data.get("blocks", []):
                    idx = int(item.get("n", 0)) - 1
                    t = str(item.get("type", "")).lower().strip()
                    if 0 <= idx < len(blocks) and t:
                        types[idx] = t
                latex = _clean_tabular(data.get("table"))
            except Exception:
                log.warning("PageAgent: bad JSON from vision agent on page %d", page_index)
        return role, types, latex

    def _apply_page_role(
        self, blocks: List[Tuple[Any, ContainerUnit]], role: str
    ) -> None:
        """Persist the vision-derived page role onto the page's blocks.

        The assembler reads metadata['page_role'] to decide between positional
        and reflow rendering (RFC 0021 §3). Without this the classification was
        computed, logged and thrown away, and every page fell back to reflow.
        """
        if not role:
            return
        for b, _ in blocks:
            md = getattr(b, "metadata", None)
            if not isinstance(md, dict):
                md = {}
                b.metadata = md
            md["page_role"] = role
            md["page_role_source"] = "PageAgent"

    def _apply_types(
        self, blocks: List[Tuple[Any, ContainerUnit]], types: Dict[int, str]
    ) -> None:
        """Record the agent-suggested type in each block's metadata."""
        for idx, t in types.items():
            if not (0 <= idx < len(blocks)):
                continue
            b, _ = blocks[idx]
            # metadata can be None on freshly-loaded blocks — always guarantee a dict.
            md = getattr(b, "metadata", None)
            if not isinstance(md, dict):
                md = {}
                b.metadata = md
            md["llm_suggested_type"] = t
            md["llm_source"] = "PageAgent"
            b.classification_confidence = 0.9
            if hasattr(b, "update_confidence"):
                b.update_confidence()

    def _recognize_table(
        self, pdf_path: str, page_index: int, host: str,
        blocks: List[Tuple[Any, ContainerUnit]],
        kind: str = "multimodel", model: Optional[str] = None,
    ) -> Optional[str]:
        """Render the page region covering these blocks and send to the agent."""
        import pymupdf as fitz

        region = union_bbox([b for b, _ in blocks], pad=0.02)
        if region is None:
            return None

        pdf = fitz.open(pdf_path)
        try:
            page = pdf[page_index]
            pw, ph = page.rect.width, page.rect.height
            clip = fitz.Rect(
                region.x0 * pw, region.y0 * ph, region.x1 * pw, region.y1 * ph
            )
            png = _pixmap_to_jpeg(page.get_pixmap(clip=clip, dpi=72))
        finally:
            pdf.close()

        return _clean_tabular(
            call_infer(host, "table", png, kind=kind, model=model)
        )

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
        table = TableBlock(
            id=derive_composite_id("agent-table", *[b.id for b, _ in blocks]),
            grid=[[TableCell(content=[])]],
        )
        # Keep the region the table actually occupies (RFC 0021 §5.4) — a
        # whole-page box would tell the assembler this spans the entire sheet.
        table.visual_layout = VisualLayout(
            bounding_box=union_bbox([b for b, _ in blocks])
            or NormalizedRect(0.0, 0.0, 1.0, 1.0),
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
