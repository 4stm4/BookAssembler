"""
PageAgentAnalyzer — pipeline stage that pulls a vision agent into extraction.

With a vision agent, every page with content is rendered and sent for
classification: the reply carries the page role (title/toc/table/…), a type for
each listed block, and — when the page is a table — its LaTeX, all in one
request. Absorbed source blocks are tombstoned, never deleted (RFC 0001 §2.4).

Requests for different pages are independent and go out concurrently, though
only a little: the cost is generation on one GPU, not transfer. Replies are
collected without touching the KRM, then applied strictly in page order — the
tree must not depend on which response arrived first (RFC 0009 §5.2).

Without a vision agent only `table`-role recognition is available, and then the
old heuristics still gate which pages are worth a request.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from src.agents import call_infer, pick
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

log = logging.getLogger(__name__)

MIN_NUMERIC_RATIO = 0.35  # numeric density hint (real tables have ≥35% numeric)
MIN_BLOCKS = 5            # need enough blocks to look like a grid
MIN_SHORT_RATIO = 0.7     # most blocks are short (labels/cells, not paragraphs)

# Requests in flight. Modest on purpose: a page costs ~1.7s of inference and
# almost nothing in transfer, so there is little latency to hide, and a queue of
# concurrent generations on one GPU only makes each of them slower.
VISION_CONCURRENCY = int(os.environ.get("KAE_VISION_CONCURRENCY", "2"))
# One systematically bad page must not abort the book, but a dead agent should
# stop the run rather than time out once per page.
FAILURE_BUDGET_RATIO = 0.35
MIN_FAILURE_BUDGET = 3

# Image fidelity. Measured against Qwen2.5-VL: a 512px page answers in ~1.7s,
# a 900px one did not return within 180s — inference cost climbs steeply with
# visual tokens, while the transfer is negligible either way (the uplink does
# ~300 KB/s, so an 8KB page leaves in milliseconds). Raise only against a timing
# measurement on the target GPU, never as a default "improvement".
RENDER_DPI = int(os.environ.get("KAE_VISION_DPI", "72"))
JPEG_QUALITY = int(os.environ.get("KAE_VISION_JPEG_QUALITY", "30"))
JPEG_MAX_DIM = int(os.environ.get("KAE_VISION_MAX_DIM", "512"))


@dataclass
class _PageResult:
    """What the agent said about one page. Carries no KRM references."""
    role: str = "text"
    types: Dict[int, str] = field(default_factory=dict)
    table_latex: Optional[str] = None
    failed: bool = False


def _pixmap_to_jpeg(
    pixmap: Any, quality: int = JPEG_QUALITY, max_dim: int = JPEG_MAX_DIM,
) -> bytes:
    import io
    from PIL import Image
    img = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _clean_tabular(raw: Any) -> Optional[str]:
    """Return a LaTeX tabular from a model reply, or None if there is none.

    Models wrap code in markdown fences often enough that accepting the raw
    string would put ``` into the document.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or "tabular" not in s.lower():
        return None
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    return s or None


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
        results: Dict[int, _PageResult] = {}
        failures = 0
        budget = max(MIN_FAILURE_BUDGET, int(len(candidates) * FAILURE_BUDGET_RATIO))
        started = time.time()

        with ThreadPoolExecutor(max_workers=VISION_CONCURRENCY) as pool:
            futures = {
                pool.submit(
                    self._analyze_page, pdf_path, pg, host, blocks,
                    classify_mode, kind, model,
                ): pg
                for pg, blocks in candidates
            }
            for fut in as_completed(futures):
                pg = futures[fut]
                try:
                    results[pg] = fut.result()
                except Exception as exc:
                    failures += 1
                    results[pg] = _PageResult(failed=True)
                    log.warning("PageAgent: page %d failed: %s", pg, exc)
                if failures > budget:
                    # A dead agent should stop the run; one bad page should not.
                    log.warning(
                        "PageAgent: %d failures over budget %d — cancelling rest",
                        failures, budget,
                    )
                    for f in futures:
                        f.cancel()
                    break

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


def _resolve_source_path(doc: KnowledgeDocument) -> Optional[str]:
    """Best-effort: resolve doc.source_uri to a local PDF file the agent can read.

    Handles sep://<provider>/<rel> (unknown provider id): tries every known
    SEP root; also file:// and absolute paths.
    """
    uri = doc.source_uri or ""
    if uri.startswith("file://"):
        p = uri[len("file://") :]
        return p if os.path.exists(p) else None
    if uri.startswith("upload://"):
        filename = uri.replace("upload://", "")
        ssd = os.environ.get("KAE_SSD_PATH", "/data/kae")
        for d in os.listdir(ssd) if os.path.isdir(ssd) else []:
            cand = os.path.join(ssd, d, filename)
            if os.path.isfile(cand):
                return cand
        return None
    if uri.startswith("sep://"):
        try:
            _, rel = uri.replace("sep://", "").split("/", 1)
        except ValueError:
            return None
        # Try both the env-configured SSD path and legacy /data/kae — SEP root
        # can move between deploys, but the file layout under it is stable.
        roots = [
            os.environ.get("KAE_SSD_PATH", "/data/kae"),
            "/data/kae", "/data/ssd",
        ]
        for root in roots:
            cand = os.path.join(root, rel)
            if os.path.exists(cand):
                return cand
        return None
    return uri if os.path.isabs(uri) and os.path.exists(uri) else None
