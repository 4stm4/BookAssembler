"""
FastAPI REST API Layer for Knowledge Assembly Engine (KAE).

Implements REST API endpoints according to KAE specifications:
- POST /api/v1/documents/upload
- GET /api/v1/jobs/{job_id}/status
- GET /api/v1/hitl/pending
- POST /api/v1/hitl/correct
- GET /api/v1/graph/{job_id}
- GET /api/v1/sep/providers
- POST /api/v1/sep/providers
- GET /api/v1/sep/providers/{provider_id}/browse
- POST /api/v1/sep/providers/{provider_id}/import

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Integrates JobManager, HITLManager, ArtifactStore, KnowledgeDocument, and SEPManager
"""

import asyncio
import io
import json
import logging
import os
from typing import Any, AsyncGenerator, BinaryIO, Dict, List, Optional
from uuid import uuid4

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from src.adapters import create_default_registry
from src.ai_layer.chunker import SemanticChunker
from src.ai_layer.exporter import AIKnowledgeExporter
from src.analyzers import PipelineRunner, create_default_pipeline
from src.audit.logger import AuditLogger
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.adapters.providers import (
    BaseSEPProvider,
    RemoteFileItem,
    SEPConfig,
    SEPManager,
    SEPType,
)
from src.artifacts.store import ArtifactStore
from src.hitl.manager import CorrectionStatus, HITLManager, HITLTaskItem
from src.jobs.manager import JobManager, JobRecord, JobStatus
from src.jobs.pyjobkit_bridge import PyJobKitBridge
from src.krm.models import (
    AlgorithmBlock,
    BaseKRMNode,
    BibEntryBlock,
    CalloutBlock,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    DiagramBlock,
    EphemeraBlock,
    FigureBlock,
    FootnoteBlock,
    FormulaBlock,
    IndexEntryBlock,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    ParagraphBlock,
    SidebarBlock,
    TocEntryBlock,
    StyledTextSpan,
    TableBlock,
    TableCell,
    TextLineInline,
    BlankPageBlock,
    TitlePageBlock,
)


# --- Pydantic Schemas ---

class DocumentUploadRequest(BaseModel):
    source_uri: Optional[str] = None
    content: Optional[str] = None


class DocumentUploadResponse(BaseModel):
    job_id: str
    status: str
    source_uri: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    source_uri: str
    created_at: str
    updated_at: str
    error_message: Optional[str] = None


class HITLTaskResponse(BaseModel):
    task_id: str
    target_krm_id: str
    current_confidence: float
    status: str
    suggested_fix: Dict[str, Any]
    reviewer_id: Optional[str] = None


class HumanCorrectionRequest(BaseModel):
    task_id: str
    reviewer_id: str
    correction_payload: Dict[str, Any] = Field(default_factory=dict)


class HumanCorrectionResponse(BaseModel):
    status: str
    task_id: str
    reviewer_id: str


class GraphVisualizationResponse(BaseModel):
    job_id: str
    knowledge_graph: Dict[str, Any]
    reading_graph: Dict[str, Any]


# --- SEP Pydantic Schemas ---

class SEPProviderCreateRequest(BaseModel):
    name: str
    sep_type: str
    credentials: Dict[str, str] = Field(default_factory=dict)
    options: Dict[str, Any] = Field(default_factory=dict)


class SEPProviderResponse(BaseModel):
    provider_id: str
    name: str
    sep_type: str
    is_active: bool


class RemoteFileItemResponse(BaseModel):
    file_id: str
    name: str
    is_directory: bool
    size_bytes: int
    mime_type: str
    path: str
    modified_at_utc: str


class SEPImportRequest(BaseModel):
    file_id: str


class SEPImportResponse(BaseModel):
    job_id: str
    status: str
    source_uri: str


# --- Global Application State & Factory ---

def create_app() -> FastAPI:
    """
    Application factory for Knowledge Assembly Engine REST API.
    """
    app = FastAPI(
        title="Knowledge Assembly Engine API",
        version="1.0.0",
        description="REST API for document ingestion, jobs tracking, HITL verification, graph visualizer, and SEP endpoints",
    )

    job_manager = JobManager()
    hitl_manager = HITLManager()
    artifact_store = ArtifactStore()
    sep_manager = SEPManager()
    pyjobkit_bridge = PyJobKitBridge()
    adapter_registry = create_default_registry()
    audit_logger = AuditLogger(log_dir=os.environ.get("KAE_DATA_DIR", ".kae"))

    app.state.pyjobkit_bridge = pyjobkit_bridge

    # Auto-register NVMe SEP provider from environment
    kae_ssd_path = os.environ.get("KAE_SSD_PATH", "/data/kae")
    if os.path.isdir(kae_ssd_path):
        nvme_config = SEPConfig(
            name="RPi5 NVMe SSD (HAT+)",
            sep_type=SEPType.LOCAL_FS,
            # Stable id so sep:// source URIs survive restarts (was random uuid4).
            provider_id="nvme-local",
            options={"root_path": kae_ssd_path},
        )
        sep_manager.register_provider(nvme_config)

    @app.on_event("startup")
    async def startup_event() -> None:
        _load_persisted_docs()
        pyjobkit_bridge.start_worker()

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        await pyjobkit_bridge.stop_worker()

    def _count_nodes(doc: KnowledgeDocument) -> int:
        count = 0
        def walk(children: list) -> None:  # type: ignore[type-arg]
            nonlocal count
            for child in children:
                if getattr(child, "is_tombstoned", False):
                    continue
                count += 1
                if isinstance(child, ContainerUnit):
                    walk(child.children)
        for c in doc.root_containers:
            if getattr(c, "is_tombstoned", False):
                continue
            count += 1
            walk(c.children)
        return count

    def _serialize_lines(node: Any) -> List[Dict[str, Any]]:
        """Inlines that carry their own bbox, as flat {text, bbox, style}.

        Set when a merged block kept the geometry of the source lines it
        absorbed (RFC 0021 §5.4); empty for ordinary single-line blocks.
        """
        out: List[Dict[str, Any]] = []
        for inline in (getattr(node, "inlines", None) or []):
            vl = getattr(inline, "visual_layout", None)
            bb = getattr(vl, "bounding_box", None) if vl else None
            if not bb:
                continue
            text = " ".join(
                s.text for s in getattr(inline, "spans", []) if hasattr(s, "text")
            ).strip()
            if not text:
                continue
            entry: Dict[str, Any] = {
                "text": text,
                "bbox": [bb.x0, bb.y0, bb.x1, bb.y1],
            }
            st = getattr(vl, "style", None)
            if st:
                entry["style"] = {
                    "font_family": st.font_family,
                    "font_size_pt": st.font_size_pt,
                    "is_bold": st.is_bold,
                    "is_italic": st.is_italic,
                    "is_monospace": st.is_monospace,
                    "text_color_rgb": list(st.text_color_rgb),
                }
            out.append(entry)
        return out if len(out) > 1 else []

    def _serialize_document(doc: KnowledgeDocument) -> Dict[str, Any]:
        def _first_page(node: Any) -> Optional[int]:
            """Smallest page index found anywhere in this node's subtree."""
            vl = getattr(node, "visual_layout", None)
            if vl is not None:
                pi = getattr(vl, "page_or_screen_index", None)
                if isinstance(pi, int):
                    return pi
            best: Optional[int] = None
            for child in getattr(node, "children", []) or []:
                if getattr(child, "is_tombstoned", False):
                    continue
                cp = _first_page(child)
                if cp is not None and (best is None or cp < best):
                    best = cp
            return best

        def _last_page(node: Any) -> Optional[int]:
            """Largest page index anywhere in this node's subtree."""
            vl = getattr(node, "visual_layout", None)
            best: Optional[int] = None
            if vl is not None:
                pi = getattr(vl, "page_or_screen_index", None)
                if isinstance(pi, int):
                    best = pi
            for child in getattr(node, "children", []) or []:
                if getattr(child, "is_tombstoned", False):
                    continue
                cp = _last_page(child)
                if cp is not None and (best is None or cp > best):
                    best = cp
            return best

        def _layout_into(result: Dict[str, Any], node: Any) -> None:
            """Persist real bounding box + typography so page layout survives round-trip."""
            vl = getattr(node, "visual_layout", None)
            if vl is None:
                return
            pi = getattr(vl, "page_or_screen_index", None)
            if isinstance(pi, int):
                result["page_index"] = pi
            bb = getattr(vl, "bounding_box", None)
            if bb is not None:
                result["bbox"] = [bb.x0, bb.y0, bb.x1, bb.y1]
            st = getattr(vl, "style", None)
            if st is not None:
                result["style"] = {
                    "font_family": st.font_family,
                    "font_size_pt": st.font_size_pt,
                    "is_bold": st.is_bold,
                    "is_italic": st.is_italic,
                    "is_monospace": st.is_monospace,
                    "text_color_rgb": list(st.text_color_rgb),
                }

        def serialize_node(node: Any) -> Dict[str, Any]:
            result = _serialize_body(node)
            # Uniformly attach real page/bbox/style from visual_layout (RFC 0002),
            # falling back to subtree's first page so every node keeps a page number.
            _layout_into(result, node)
            # Per-line geometry, for any block whose inlines kept it. A block is
            # one PDF text block, which can span several laid-out lines; without
            # them the editor can only draw one box for a whole contents list
            # (RFC 0021 §3, §5.4).
            if "lines" not in result:
                lines = _serialize_lines(node)
                if lines:
                    result["lines"] = lines
            if "page_index" not in result:
                cp = _first_page(node)
                if cp is not None:
                    result["page_index"] = cp
            # Containers span a page range — expose the last page so the UI can
            # show "стр.N–M" instead of just the first page.
            if isinstance(node, ContainerUnit):
                lp = _last_page(node)
                if lp is not None and lp != result.get("page_index"):
                    result["page_end"] = lp
            # Expose useful metadata to the UI: translations, agent-suggested type,
            # toc-entry parts, etc. (skip internal-only keys).
            md = getattr(node, "metadata", None) or {}
            if md:
                slim = {k: v for k, v in md.items() if k not in ("tombstone_reason",)}
                if slim:
                    result["metadata"] = slim
            return result

        def _serialize_body(node: Any) -> Dict[str, Any]:
            if isinstance(node, ContainerUnit):
                result = {
                    "id": node.id,
                    "type": "ContainerUnit",
                    "title": node.title,
                    "level": node.level,
                    "confidence_score": node.confidence_score,
                    "extraction_confidence": node.extraction_confidence,
                    "classification_confidence": node.classification_confidence,
                    "children": [
                        serialize_node(c) for c in node.children
                        if not getattr(c, "is_tombstoned", False)
                    ],
                }
                if node.semantic_type:
                    result["semantic_type"] = node.semantic_type
                cp = _first_page(node)
                if cp is not None:
                    result["page_index"] = cp
                return result
            elif isinstance(node, BlankPageBlock):
                result = {
                    "id": node.id,
                    "type": "BlankPageBlock",
                    "text": "",
                    "confidence_score": 1.0,
                }
                vl = getattr(node, "visual_layout", None)
                if vl and hasattr(vl, "page_or_screen_index"):
                    result["page_index"] = vl.page_or_screen_index
                return result
            elif isinstance(node, TitlePageBlock):
                text_parts = []
                for inline in (node.inlines or []):
                    for span in getattr(inline, "spans", []):
                        if hasattr(span, "text"):
                            text_parts.append(span.text)
                result = {
                    "id": node.id,
                    "type": "TitlePageBlock",
                    "text": "\n".join(text_parts),
                    "book_title": node.book_title,
                    "authors": node.authors,
                    "publisher": node.publisher,
                    "page_role": node.page_role,
                    "confidence_score": node.confidence_score,
                    "extraction_confidence": node.extraction_confidence,
                    "classification_confidence": node.classification_confidence,
                }
                vl = getattr(node, "visual_layout", None)
                if vl and hasattr(vl, "page_or_screen_index"):
                    result["page_index"] = vl.page_or_screen_index
                if vl and getattr(vl, "bounding_box", None):
                    bb = vl.bounding_box
                    result["bbox"] = [bb.x0, bb.y0, bb.x1, bb.y1]
                # Per-line geometry of the merged sources (RFC 0021 §5.4) — what
                # lets the editor place a title page instead of drawing one box.
                lines = _serialize_lines(node)
                if lines:
                    result["lines"] = lines
                return result
            elif isinstance(node, ParagraphBlock):
                text_parts = []
                for inline in (node.inlines or []):
                    if hasattr(inline, "spans"):
                        for span in inline.spans:
                            if hasattr(span, "text"):
                                text_parts.append(span.text)
                result = {
                    "id": node.id,
                    "type": "ParagraphBlock",
                    "text": " ".join(text_parts),
                    "confidence_score": node.confidence_score,
                    "extraction_confidence": node.extraction_confidence,
                    "classification_confidence": node.classification_confidence,
                }
                vl = getattr(node, "visual_layout", None)
                if vl and hasattr(vl, "page_or_screen_index"):
                    result["page_index"] = vl.page_or_screen_index
                return result
            elif isinstance(node, CodeBlock):
                return {
                    "id": node.id,
                    "type": "CodeBlock",
                    "text": node.code_text or "",
                    "confidence_score": node.confidence_score,
                }
            elif isinstance(node, DiagramBlock):
                # Must precede FigureBlock (DiagramBlock subclasses it).
                return {
                    "id": node.id,
                    "type": "DiagramBlock",
                    "caption_text": node.caption_text,
                    "labels": node.labels,
                    "confidence_score": node.confidence_score,
                    "extraction_confidence": node.extraction_confidence,
                    "classification_confidence": node.classification_confidence,
                }
            elif isinstance(node, FigureBlock):
                return {
                    "id": node.id,
                    "type": "FigureBlock",
                    "image_uri": node.image_uri or "",
                    "confidence_score": node.confidence_score,
                }
            elif isinstance(node, FormulaBlock):
                return {
                    "id": node.id,
                    "type": "FormulaBlock",
                    "text": node.latex_expression or "",
                    "confidence_score": node.confidence_score,
                }
            elif isinstance(node, CaptionBlock):
                result = {
                    "id": node.id,
                    "type": "CaptionBlock",
                    "text": node.caption_text,
                    "target_type": node.target_type,
                    "label_number": node.label_number,
                    "target_block_id": node.target_block_id,
                    "confidence_score": node.confidence_score,
                    "extraction_confidence": node.extraction_confidence,
                    "classification_confidence": node.classification_confidence,
                }
                vl = getattr(node, "visual_layout", None)
                if vl and hasattr(vl, "page_or_screen_index"):
                    result["page_index"] = vl.page_or_screen_index
                return result
            elif isinstance(node, BibEntryBlock):
                result = {
                    "id": node.id,
                    "type": "BibEntryBlock",
                    "cite_key": node.cite_key,
                    "authors": node.authors,
                    "year": node.year,
                    "title": node.title,
                    "text": node.raw_text,
                    "confidence_score": node.confidence_score,
                }
                vl = getattr(node, "visual_layout", None)
                if vl and hasattr(vl, "page_or_screen_index"):
                    result["page_index"] = vl.page_or_screen_index
                return result
            elif isinstance(node, FootnoteBlock):
                result = {
                    "id": node.id,
                    "type": "FootnoteBlock",
                    "marker": node.marker,
                    "footnote_number": node.footnote_number,
                    "text": node.text,
                    "ref_block_ids": list(node.ref_block_ids),
                    "confidence_score": node.confidence_score,
                }
                vl = getattr(node, "visual_layout", None)
                if vl and hasattr(vl, "page_or_screen_index"):
                    result["page_index"] = vl.page_or_screen_index
                return result
            elif isinstance(node, CalloutBlock):
                result = {
                    "id": node.id,
                    "type": "CalloutBlock",
                    "kind": node.kind,
                    "severity": node.severity,
                    "label": node.label,
                    "content": [
                        serialize_node(b) for b in node.content
                        if not getattr(b, "is_tombstoned", False)
                    ],
                    "confidence_score": node.confidence_score,
                }
                vl = getattr(node, "visual_layout", None)
                if vl and hasattr(vl, "page_or_screen_index"):
                    result["page_index"] = vl.page_or_screen_index
                return result
            elif isinstance(node, TocEntryBlock):
                result = {
                    "id": node.id,
                    "type": "TocEntryBlock",
                    "text": node.entry_text,
                    "chapter_number": node.chapter_number,
                    "target_page": node.target_page,
                    "anchor_id": node.anchor_id,
                    "confidence_score": node.confidence_score,
                    "extraction_confidence": node.extraction_confidence,
                    "classification_confidence": node.classification_confidence,
                }
                vl = getattr(node, "visual_layout", None)
                if vl and hasattr(vl, "page_or_screen_index"):
                    result["page_index"] = vl.page_or_screen_index
                return result
            elif isinstance(node, ListBlock):
                result = {
                    "id": node.id,
                    "type": "ListBlock",
                    "list_style": node.list_style,
                    "items": [
                        {
                            "id": it.id,
                            "type": "ListItemBlock",
                            "marker": it.marker,
                            "content": [
                                serialize_node(b) for b in it.content
                                if not getattr(b, "is_tombstoned", False)
                            ],
                        }
                        for it in node.items
                        if not getattr(it, "is_tombstoned", False)
                    ],
                    "confidence_score": node.confidence_score,
                }
                vl = getattr(node, "visual_layout", None)
                if vl and hasattr(vl, "page_or_screen_index"):
                    result["page_index"] = vl.page_or_screen_index
                return result
            elif isinstance(node, TableBlock):
                rows = []
                for row in node.grid:
                    cells = []
                    for cell in row:
                        cell_text = ""
                        for content in cell.content:
                            if isinstance(content, ParagraphBlock):
                                for inline in (content.inlines or []):
                                    for span in getattr(inline, "spans", []):
                                        if hasattr(span, "text"):
                                            cell_text += span.text
                        cells.append(cell_text)
                    rows.append(cells)
                result = {
                    "id": node.id,
                    "type": "TableBlock",
                    "rows": rows,
                    "confidence_score": node.confidence_score,
                }
                vl = getattr(node, "visual_layout", None)
                if vl:
                    if hasattr(vl, "page_or_screen_index"):
                        result["page_index"] = vl.page_or_screen_index
                    bb = getattr(vl, "bounding_box", None)
                    if bb:
                        result["bbox"] = [bb.x0, bb.y0, bb.x1, bb.y1]
                return result
            elif isinstance(node, EphemeraBlock):
                return {
                    "id": node.id,
                    "type": "EphemeraBlock",
                    "ephemera_type": node.ephemera_type,
                    "repeated_text": node.repeated_text,
                    # The UI reads "text"; without it a running head renders as
                    # an empty box on the reconstructed page.
                    "text": node.repeated_text,
                    "confidence_score": node.confidence_score,
                }
            elif isinstance(node, AlgorithmBlock):
                return {
                    "id": node.id,
                    "type": "AlgorithmBlock",
                    "algorithm_name": node.algorithm_name,
                    "algorithm_number": node.algorithm_number,
                    "pseudocode": node.pseudocode,
                    "confidence_score": node.confidence_score,
                }
            elif isinstance(node, SidebarBlock):
                children = [
                    serialize_node(c) for c in node.content
                    if not getattr(c, "is_tombstoned", False)
                ]
                return {
                    "id": node.id,
                    "type": "SidebarBlock",
                    "sidebar_type": node.sidebar_type,
                    "content": children,
                    "confidence_score": node.confidence_score,
                }
            elif isinstance(node, IndexEntryBlock):
                subs = [
                    {"term": s.term, "page_refs": s.page_refs}
                    for s in node.subentries
                ] if node.subentries else []
                return {
                    "id": node.id,
                    "type": "IndexEntryBlock",
                    "term": node.term,
                    "page_refs": node.page_refs,
                    "subentries": subs,
                    "confidence_score": node.confidence_score,
                }
            fallback = {"id": getattr(node, "id", ""), "type": type(node).__name__}
            cp = _first_page(node)
            if cp is not None:
                fallback["page_index"] = cp
            return fallback

        # Forward-fill page numbers: every element sits on a physical page, so any
        # node missing an explicit page_index inherits the last one seen in reading order.
        def _fill_pages(nodes: List[Dict[str, Any]], last: List[Optional[int]]) -> None:
            for n in nodes:
                if isinstance(n.get("page_index"), int):
                    last[0] = n["page_index"]
                elif last[0] is not None:
                    n["page_index"] = last[0]
                if n.get("children"):
                    _fill_pages(n["children"], last)

        serialized = [
            serialize_node(c) for c in doc.root_containers
            if not getattr(c, "is_tombstoned", False)
        ]
        _fill_pages(serialized, [None])

        semantic = []
        for su in getattr(doc, "semantic_units", []) or []:
            entry: Dict[str, Any] = {
                "id": su.id,
                "kind": type(su).__name__,
                "target_block_id": getattr(su, "target_block_id", ""),
            }
            for attr in ("statement_type", "name", "number", "proved_statement_id",
                         "term", "definition_text", "severity", "message_text",
                         "architecture_or_platform", "mnemonic_or_function",
                         "operands_or_arguments", "affected_flags_or_state"):
                val = getattr(su, attr, None)
                if val is not None and val != "" and val != []:
                    entry[attr] = val
            semantic.append(entry)

        return {
            "title": doc.title,
            "source_uri": doc.source_uri,
            "source_type": doc.source_type,
            "page_count": doc.metadata.get("page_count", 0) if doc.metadata else 0,
            "containers": serialized,
            "semantic_units": semantic,
        }

    def _rebuild_document(data: Dict[str, Any]) -> KnowledgeDocument:
        def _restore_layout(node: Any, n: Dict[str, Any]) -> None:
            pg = n.get("page_index")
            if pg is not None:
                from src.krm.models import VisualLayout, NormalizedRect, StyleDescriptor
                bb = n.get("bbox")
                if isinstance(bb, list) and len(bb) == 4:
                    # Clamp to KRM invariant #3: coords in [0,1], x0<=x1, y0<=y1.
                    x0, y0, x1, y1 = (max(0.0, min(1.0, float(v))) for v in bb)
                    if x0 > x1:
                        x0, x1 = x1, x0
                    if y0 > y1:
                        y0, y1 = y1, y0
                    rect = NormalizedRect(x0, y0, x1, y1)
                else:
                    rect = NormalizedRect(0.0, 0.0, 1.0, 1.0)
                style = None
                sd = n.get("style")
                if isinstance(sd, dict):
                    style = StyleDescriptor(
                        font_family=sd.get("font_family", "sans-serif"),
                        font_size_pt=float(sd.get("font_size_pt", 12.0)),
                        is_bold=bool(sd.get("is_bold", False)),
                        is_italic=bool(sd.get("is_italic", False)),
                        is_monospace=bool(sd.get("is_monospace", False)),
                        text_color_rgb=tuple(sd.get("text_color_rgb", [0, 0, 0])),
                    )
                node.visual_layout = VisualLayout(
                    bounding_box=rect,
                    page_or_screen_index=pg,
                    style=style,
                )
            ec = n.get("extraction_confidence")
            if ec is not None:
                node.extraction_confidence = ec
            cc = n.get("classification_confidence")
            if cc is not None:
                node.classification_confidence = cc

        def rebuild_node(n: Dict[str, Any]) -> Any:
            t = n.get("type", "")
            if t == "ContainerUnit":
                c = ContainerUnit(
                    title=n.get("title", ""),
                    level=n.get("level", 1),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                c.id = n.get("id", c.id)
                if n.get("semantic_type"):
                    c.semantic_type = n["semantic_type"]
                _restore_layout(c, n)
                for ch in n.get("children", []):
                    c.children.append(rebuild_node(ch))
                return c
            elif t == "ParagraphBlock":
                p = ParagraphBlock(
                    confidence_score=n.get("confidence_score", 1.0),
                    inlines=[TextLineInline(spans=[StyledTextSpan(text=n.get("text", ""))])],
                )
                p.id = n.get("id", p.id)
                _restore_layout(p, n)
                return p
            elif t == "CodeBlock":
                cb = CodeBlock(
                    code_text=n.get("text", ""),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                cb.id = n.get("id", cb.id)
                _restore_layout(cb, n)
                return cb
            elif t == "BlankPageBlock":
                bp = BlankPageBlock(confidence_score=1.0)
                bp.id = n.get("id", bp.id)
                _restore_layout(bp, n)
                return bp
            elif t == "TitlePageBlock":
                tp = TitlePageBlock(
                    book_title=n.get("book_title", ""),
                    authors=n.get("authors", []),
                    publisher=n.get("publisher", ""),
                    page_role=n.get("page_role", "title"),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                tp.id = n.get("id", tp.id)
                text = n.get("text", "")
                if text:
                    tp.inlines = [TextLineInline(spans=[StyledTextSpan(text=text)])]
                _restore_layout(tp, n)
                return tp
            elif t == "DiagramBlock":
                dg = DiagramBlock(
                    caption_text=n.get("caption_text", ""),
                    labels=n.get("labels", []),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                dg.id = n.get("id", dg.id)
                _restore_layout(dg, n)
                return dg
            elif t == "FigureBlock":
                fb = FigureBlock(
                    image_uri=n.get("image_uri", ""),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                fb.id = n.get("id", fb.id)
                _restore_layout(fb, n)
                return fb
            elif t == "FormulaBlock":
                fm = FormulaBlock(
                    latex_expression=n.get("text", ""),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                fm.id = n.get("id", fm.id)
                _restore_layout(fm, n)
                return fm
            elif t == "CaptionBlock":
                cap = CaptionBlock(
                    caption_text=n.get("text", ""),
                    target_type=n.get("target_type", ""),
                    label_number=n.get("label_number"),
                    target_block_id=n.get("target_block_id"),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                cap.id = n.get("id", cap.id)
                _restore_layout(cap, n)
                return cap
            elif t == "BibEntryBlock":
                be = BibEntryBlock(
                    cite_key=n.get("cite_key", ""),
                    authors=list(n.get("authors", []) or []),
                    year=n.get("year"),
                    title=n.get("title", ""),
                    raw_text=n.get("text", ""),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                be.id = n.get("id", be.id)
                _restore_layout(be, n)
                return be
            elif t == "FootnoteBlock":
                fn = FootnoteBlock(
                    marker=n.get("marker", ""),
                    footnote_number=n.get("footnote_number"),
                    text=n.get("text", ""),
                    ref_block_ids=list(n.get("ref_block_ids", []) or []),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                fn.id = n.get("id", fn.id)
                _restore_layout(fn, n)
                return fn
            elif t == "CalloutBlock":
                cb = CalloutBlock(
                    kind=n.get("kind", "note"),
                    severity=n.get("severity", "info"),
                    label=n.get("label", ""),
                    content=[rebuild_node(b) for b in n.get("content", [])],
                    confidence_score=n.get("confidence_score", 1.0),
                )
                cb.id = n.get("id", cb.id)
                _restore_layout(cb, n)
                return cb
            elif t == "TocEntryBlock":
                te = TocEntryBlock(
                    entry_text=n.get("text", ""),
                    chapter_number=n.get("chapter_number"),
                    target_page=n.get("target_page"),
                    anchor_id=n.get("anchor_id"),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                te.id = n.get("id", te.id)
                _restore_layout(te, n)
                return te
            elif t == "ListBlock":
                items: List[ListItemBlock] = []
                for it in n.get("items", []):
                    li = ListItemBlock(
                        marker=it.get("marker", ""),
                        content=[rebuild_node(b) for b in it.get("content", [])],
                    )
                    li.id = it.get("id", li.id)
                    items.append(li)
                lb = ListBlock(
                    list_style=n.get("list_style", "bullet"),
                    items=items,
                    confidence_score=n.get("confidence_score", 1.0),
                )
                lb.id = n.get("id", lb.id)
                _restore_layout(lb, n)
                return lb
            elif t == "TableBlock":
                grid = []
                for row in n.get("rows", []):
                    cells = []
                    for cell_text in row:
                        cell = TableCell(
                            content=[ParagraphBlock(
                                inlines=[TextLineInline(spans=[StyledTextSpan(text=cell_text)])]
                            )]
                        )
                        cells.append(cell)
                    grid.append(cells)
                tb = TableBlock(grid=grid, confidence_score=n.get("confidence_score", 1.0))
                tb.id = n.get("id", tb.id)
                _restore_layout(tb, n)
                return tb
            return ContainerUnit(title=n.get("title", "unknown"))

        doc = KnowledgeDocument(
            title=data.get("title", ""),
            source_uri=data.get("_source_uri", data.get("source_uri", "")),
            source_type=data.get("_source_type", data.get("source_type", "pdf")),
            metadata={"page_count": data.get("page_count", 0)},
        )
        for c in data.get("containers", []):
            doc.root_containers.append(rebuild_node(c))

        from src.krm.models import (
            TheoremSpec, ProofSpec, ExampleSpec, RemarkSpec,
            DefinitionSpec, InstructionSpec, WarningSpec,
        )
        _SU_MAP = {
            "TheoremSpec": TheoremSpec, "ProofSpec": ProofSpec,
            "ExampleSpec": ExampleSpec, "RemarkSpec": RemarkSpec,
            "DefinitionSpec": DefinitionSpec, "InstructionSpec": InstructionSpec,
            "WarningSpec": WarningSpec,
        }
        for su_data in data.get("semantic_units", []):
            cls = _SU_MAP.get(su_data.get("kind", ""))
            if cls is None:
                continue
            kwargs: Dict[str, Any] = {"target_block_id": su_data.get("target_block_id", "")}
            for field_name in ("statement_type", "name", "number", "proved_statement_id",
                               "term", "definition_text", "severity", "message_text",
                               "architecture_or_platform", "mnemonic_or_function",
                               "operands_or_arguments", "affected_flags_or_state"):
                if field_name in su_data:
                    kwargs[field_name] = su_data[field_name]
            try:
                spec = cls(**kwargs)
                spec.id = su_data.get("id", spec.id)
                doc.semantic_units.append(spec)
            except TypeError:
                pass

        return doc

    # Persistent document store (L1 Local Disk per RFC 0013)
    docs_store: Dict[str, KnowledgeDocument] = {}
    graphs_store: Dict[str, Dict[str, Any]] = {}
    progress_store: Dict[str, Dict[str, Any]] = {}
    _docs_dir = os.path.join(os.environ.get("KAE_DATA_DIR", ".kae"), "docs")
    os.makedirs(_docs_dir, exist_ok=True)

    def _persist_doc(job_id: str, doc: KnowledgeDocument) -> None:
        path = os.path.join(_docs_dir, f"{job_id}.json")
        data = _serialize_document(doc)
        data["_source_uri"] = doc.source_uri
        data["_source_type"] = doc.source_type
        job = job_manager.get_job(job_id)
        if job:
            data["_created_at"] = job.created_at
        with open(path, "w") as f:
            json.dump(data, f)

    def _load_persisted_docs() -> None:
        for fname in os.listdir(_docs_dir):
            if not fname.endswith(".json"):
                continue
            job_id = fname[:-5]
            if job_id in docs_store:
                continue
            try:
                with open(os.path.join(_docs_dir, fname)) as f:
                    data = json.load(f)
                doc = _rebuild_document(data)
                docs_store[job_id] = doc
                job = job_manager.get_job(job_id)
                if not job:
                    job_manager.restore_job(
                        job_id, data.get("_source_uri", ""), "COMPLETED",
                        created_at=data.get("_created_at", ""),
                    )
            except Exception:
                logging.getLogger(__name__).exception(
                    "Failed to restore persisted document '%s'; skipping", job_id
                )

    @app.post(
        "/api/v1/documents/upload",
        response_model=DocumentUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_document(
        payload: Optional[DocumentUploadRequest] = None,
        file: Optional[UploadFile] = File(None),
    ) -> DocumentUploadResponse:
        """
        Uploads a document or text payload and initializes a processing Job.

        For PDF/supported files: saves the file, then parses via the appropriate
        adapter and runs the full analyzer pipeline in background.
        For text payloads: creates a simple document synchronously.
        """
        source_uri = "upload://file.txt"
        raw_bytes: Optional[bytes] = None

        if file is not None and file.filename:
            source_uri = f"upload://{file.filename}"
            raw_bytes = await file.read()
        elif payload is not None and payload.source_uri:
            source_uri = payload.source_uri

        job = job_manager.create_job(source_uri=source_uri)

        ext = ""
        if "." in source_uri:
            ext = source_uri.rsplit(".", 1)[1].lower()

        if raw_bytes and ext and adapter_registry.get_adapter_for_extension(ext):
            upload_dir = os.path.join(kae_ssd_path, job.job_id)
            os.makedirs(upload_dir, exist_ok=True)
            filename = os.path.basename(source_uri.replace("upload://", ""))
            saved_path = os.path.join(upload_dir, filename)
            with open(saved_path, "wb") as f:
                f.write(raw_bytes)

            file_stream = open(saved_path, "rb")
            job_manager.update_status(job.job_id, JobStatus.RUNNING)
            progress_store[job.job_id] = {"step": 0, "total": 10, "stage": "Запуск..."}
            asyncio.create_task(_run_pipeline_background(job, file_stream, ext))

            return DocumentUploadResponse(
                job_id=job.job_id,
                status="PROCESSING",
                source_uri=job.source_uri,
            )

        doc = KnowledgeDocument(source_uri=source_uri)
        container = ContainerUnit(title="Root Section", level=1)
        content_text = payload.content if (payload and payload.content) else ""
        if raw_bytes and not content_text:
            content_text = raw_bytes.decode("utf-8", errors="replace")
        if not content_text:
            content_text = ""
        if content_text:
            paragraph = ParagraphBlock(
                confidence_score=0.5,
                inlines=[TextLineInline(spans=[StyledTextSpan(text=content_text)])]
            )
            container.children.append(paragraph)
        doc.root_containers.append(container)

        docs_store[job.job_id] = doc
        _persist_doc(job.job_id, doc)

        rg = ReadingGraph()
        kg = KnowledgeGraph()
        pipeline = PipelineRunner(create_default_pipeline())
        pipeline.execute(doc, rg, kg)
        graphs_store[job.job_id] = {"rg": rg, "kg": kg}
        hitl_manager.flag_low_confidence_nodes(doc, threshold=0.80)
        job_manager.update_status(job.job_id, JobStatus.COMPLETED)

        return DocumentUploadResponse(
            job_id=job.job_id,
            status=job.status.value,
            source_uri=job.source_uri,
        )

    @app.get(
        "/api/v1/jobs/{job_id}/status",
        response_model=JobStatusResponse,
    )
    async def get_job_status(job_id: str) -> JobStatusResponse:
        """
        Retrieves job status and metadata by job_id.
        """
        job = job_manager.get_job(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID '{job_id}' not found",
            )

        return JobStatusResponse(
            job_id=job.job_id,
            status=job.status.value,
            source_uri=job.source_uri,
            created_at=job.created_at,
            updated_at=job.updated_at,
            error_message=job.error_message,
        )

    @app.get(
        "/api/v1/hitl/pending",
        response_model=List[HITLTaskResponse],
    )
    async def get_pending_hitl_tasks() -> List[HITLTaskResponse]:
        """
        Retrieves list of tasks requiring human verification/correction.
        """
        pending: List[HITLTaskResponse] = []
        for task in hitl_manager._tasks.values():
            if task.status == CorrectionStatus.PENDING_HUMAN_REVIEW:
                pending.append(
                    HITLTaskResponse(
                        task_id=task.task_id,
                        target_krm_id=task.target_krm_id,
                        current_confidence=task.current_confidence,
                        status=task.status.value,
                        suggested_fix=task.suggested_fix,
                        reviewer_id=task.reviewer_id,
                    )
                )
        return pending

    @app.post(
        "/api/v1/hitl/correct",
        response_model=HumanCorrectionResponse,
    )
    async def submit_human_correction(
        body: HumanCorrectionRequest,
    ) -> HumanCorrectionResponse:
        """
        Submits human correction for a flagged HITL task item.
        """
        task = hitl_manager.get_task(body.task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"HITL task with ID '{body.task_id}' not found",
            )

        # Find document containing target KRM node
        target_doc: Optional[KnowledgeDocument] = None
        for doc in docs_store.values():
            if hitl_manager._find_node_by_id(doc, task.target_krm_id) is not None:
                target_doc = doc
                break

        if target_doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document containing KRM node '{task.target_krm_id}' not found",
            )

        hitl_manager.apply_human_correction(
            doc=target_doc,
            task_id=body.task_id,
            correction_payload=body.correction_payload,
            reviewer_id=body.reviewer_id,
        )

        audit_logger.log("HITL_CORRECTION", body.reviewer_id, {
            "task_id": body.task_id,
            "target_krm_id": task.target_krm_id,
            "status": task.status.value,
        })

        return HumanCorrectionResponse(
            status=task.status.value,
            task_id=task.task_id,
            reviewer_id=body.reviewer_id,
        )

    @app.get(
        "/api/v1/graph/{job_id}",
        response_model=GraphVisualizationResponse,
    )
    async def get_graph_visualization(job_id: str) -> GraphVisualizationResponse:
        """
        Retrieves Knowledge Graph (KG) and Reading Graph (RG) visualization payloads for job_id.
        """
        job = job_manager.get_job(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job with ID '{job_id}' not found",
            )

        graphs = graphs_store.get(job_id, {})
        # Lazy rebuild: graphs live only in memory and are lost on restart.
        # If the document was restored from JSON, regenerate its graphs on demand.
        if "kg" not in graphs or "rg" not in graphs:
            doc = docs_store.get(job_id)
            if doc is not None:
                try:
                    rg = ReadingGraph()
                    kg = KnowledgeGraph()
                    pipeline = PipelineRunner(create_default_pipeline())
                    await asyncio.get_event_loop().run_in_executor(
                        None, lambda: pipeline.execute(doc, rg, kg)
                    )
                    graphs = {"rg": rg, "kg": kg}
                    graphs_store[job_id] = graphs
                except Exception:
                    logging.exception("Failed to rebuild graphs for job %s", job_id)

        kg_data = graphs["kg"].to_json_dict() if "kg" in graphs else {"graph_version": "1.0.0", "entities": [], "edges": []}
        rg_data = graphs["rg"].to_json_dict() if "rg" in graphs else {"graph_version": "1.0.0", "edges": []}

        return GraphVisualizationResponse(
            job_id=job_id,
            knowledge_graph=kg_data,
            reading_graph=rg_data,
        )

    # --- SEP REST API Endpoints ---

    @app.get(
        "/api/v1/sep/providers",
        response_model=List[SEPProviderResponse],
    )
    async def list_sep_providers() -> List[SEPProviderResponse]:
        """
        Lists all configured Storage Endpoint Providers (SEP).
        """
        configs = sep_manager.list_configured_providers()
        return [
            SEPProviderResponse(
                provider_id=c.provider_id,
                name=c.name,
                sep_type=c.sep_type.value,
                is_active=c.is_active,
            )
            for c in configs
        ]

    @app.post(
        "/api/v1/sep/providers",
        response_model=SEPProviderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_sep_provider(
        req: SEPProviderCreateRequest,
    ) -> SEPProviderResponse:
        """
        Registers and configures a new Storage Endpoint Provider.
        """
        try:
            sep_type = SEPType(req.sep_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sep_type '{req.sep_type}'. Must be one of {[e.value for e in SEPType]}",
            )

        config = SEPConfig(
            name=req.name,
            sep_type=sep_type,
            credentials=req.credentials,
            options=req.options,
        )

        sep_manager.register_provider(config)

        return SEPProviderResponse(
            provider_id=config.provider_id,
            name=config.name,
            sep_type=config.sep_type.value,
            is_active=config.is_active,
        )

    @app.get(
        "/api/v1/sep/providers/{provider_id}/browse",
        response_model=List[RemoteFileItemResponse],
    )
    async def browse_sep_provider(
        provider_id: str,
        folder_path: str = Query("/", alias="path"),
    ) -> List[RemoteFileItemResponse]:
        """
        Browses file tree / list directory for a configured SEP provider.
        """
        try:
            provider = sep_manager.get_provider(provider_id)
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SEP Provider with ID '{provider_id}' not found",
            )

        items = await provider.list_directory(folder_path=folder_path)

        return [
            RemoteFileItemResponse(
                file_id=item.file_id,
                name=item.name,
                is_directory=item.is_directory,
                size_bytes=item.size_bytes,
                mime_type=item.mime_type,
                path=item.path,
                modified_at_utc=item.modified_at_utc,
            )
            for item in items
        ]

    async def _run_pipeline_background(
        job: Any,
        file_stream: BinaryIO,
        ext: str,
    ) -> None:
        """Background task: parse file via adapter and run analyzer pipeline."""
        job_id = job.job_id
        adapter = adapter_registry.get_adapter_for_extension(ext)
        if not adapter:
            doc = KnowledgeDocument(source_uri=job.source_uri)
            container = ContainerUnit(title="Unsupported Format", level=1)
            container.children.append(
                ParagraphBlock(
                    inlines=[TextLineInline(spans=[StyledTextSpan(text=f"No adapter for .{ext}")])],
                )
            )
            doc.root_containers.append(container)
            docs_store[job_id] = doc
            progress_store[job_id] = {"step": 1, "total": 1, "stage": "done", "error": f"No adapter for .{ext}"}
            job_manager.update_status(job_id, JobStatus.FAILED, error=f"No adapter for .{ext}")
            return

        try:
            progress_store[job_id] = {"step": 0, "total": 10, "stage": "Чтение файла..."}
            await pyjobkit_bridge.publish_event({
                "event": "job_started", "job_id": job_id,
                "job_type": "import", "progress": 0.0, "status": "RUNNING",
                "stage": "Чтение файла...",
            })

            progress_store[job_id] = {"step": 1, "total": 10, "stage": "Парсинг PDF..."}
            loop = asyncio.get_event_loop()
            doc = await loop.run_in_executor(
                None, adapter.parse, file_stream, job.source_uri
            )
            docs_store[job_id] = doc
            _persist_doc(job_id, doc)

            progress_store[job_id] = {"step": 2, "total": 10, "stage": "Запуск анализаторов..."}

            rg = ReadingGraph()
            kg = KnowledgeGraph()
            pipeline = PipelineRunner(create_default_pipeline())

            def on_progress(step: int, total: int, name: str) -> None:
                current_step = 2 + step
                total_steps = 2 + total
                stage = name if name != "done" else "Завершение..."
                progress_store[job_id] = {
                    "step": current_step,
                    "total": total_steps,
                    "stage": stage,
                    "analyzer": name,
                }
                asyncio.run_coroutine_threadsafe(
                    pyjobkit_bridge.publish_event({
                        "event": "job_progress", "job_id": job_id,
                        "job_type": stage, "progress": current_step / total_steps,
                        "status": "RUNNING", "stage": stage,
                    }),
                    loop,
                )

            await loop.run_in_executor(
                None, lambda: pipeline.execute(doc, rg, kg, on_progress=on_progress)
            )
            graphs_store[job_id] = {"rg": rg, "kg": kg}
            hitl_manager.flag_low_confidence_nodes(doc, threshold=0.80)
            _persist_doc(job_id, doc)

            audit_logger.log("DOCUMENT_IMPORTED", "system", {
                "job_id": job_id, "source_uri": job.source_uri,
            })
            audit_logger.log("PIPELINE_EXECUTED", "system", {
                "job_id": job_id,
                "analyzers": [a.manifest.name for a in create_default_pipeline()],
            })

            job_manager.update_status(job_id, JobStatus.COMPLETED)
            progress_store[job_id] = {"step": 10, "total": 10, "stage": "done"}
            await pyjobkit_bridge.publish_event({
                "event": "job_completed", "job_id": job_id,
                "job_type": "import", "progress": 1.0, "status": "COMPLETED",
            })
        except Exception as parse_err:
            logging.getLogger(__name__).exception("Import failed for %s", job_id)
            doc = KnowledgeDocument(source_uri=job.source_uri)
            container = ContainerUnit(title="Parse Error", level=1)
            container.children.append(
                ParagraphBlock(
                    inlines=[TextLineInline(spans=[StyledTextSpan(text=f"Parse error: {parse_err}")])],
                )
            )
            doc.root_containers.append(container)
            docs_store[job_id] = doc
            job_manager.update_status(job_id, JobStatus.FAILED, error=str(parse_err))
            progress_store[job_id] = {"step": 0, "total": 1, "stage": "error", "error": str(parse_err)}
            await pyjobkit_bridge.publish_event({
                "event": "job_failed", "job_id": job_id,
                "job_type": "import", "progress": 0.0, "status": "FAILED",
                "error": str(parse_err),
            })

    async def _process_import_background(
        job: Any,
        provider_id: str,
        file_id: str,
        ext: str,
    ) -> None:
        """Background task: fetch file from SEP provider and process."""
        job_id = job.job_id
        try:
            sep_provider = _resolve_sep_provider(provider_id)
            file_stream = await sep_provider.get_file_stream(file_id)
        except Exception as e:
            job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
            return
        await _run_pipeline_background(job, file_stream, ext)

    @app.post(
        "/api/v1/sep/providers/{provider_id}/import",
        response_model=SEPImportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def import_from_sep_provider(
        provider_id: str,
        body: SEPImportRequest,
    ) -> SEPImportResponse:
        """
        Imports selected file from SEP provider into KAE JobManager.
        Returns immediately with PROCESSING status; work continues in background.
        """
        try:
            job = await sep_manager.import_file_to_kae(
                provider_id=provider_id,
                file_id=body.file_id,
                job_manager=job_manager,
            )
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SEP Provider with ID '{provider_id}' not found",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to import file from SEP provider: {str(exc)}",
            )

        ext = os.path.splitext(body.file_id)[1].lstrip(".")
        job_manager.update_status(job.job_id, JobStatus.RUNNING)
        progress_store[job.job_id] = {"step": 0, "total": 10, "stage": "Запуск..."}

        asyncio.create_task(_process_import_background(job, provider_id, body.file_id, ext))

        return SEPImportResponse(
            job_id=job.job_id,
            status="PROCESSING",
            source_uri=job.source_uri,
        )

    @app.get("/api/v1/jobs/{job_id}/progress")
    async def get_job_progress(job_id: str) -> Dict[str, Any]:
        job = job_manager.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        progress = progress_store.get(job_id, {})
        return {
            "job_id": job_id,
            "status": job.status.value,
            "step": progress.get("step", 0),
            "total": progress.get("total", 1),
            "stage": progress.get("stage", ""),
            "error": progress.get("error"),
        }

    # --- Document & Job Result Endpoints ---

    def _avg_confidence(doc: KnowledgeDocument) -> float:
        """Mean confidence over the leaves that carry one.

        Containers have no meaningful score of their own, so averaging them in
        would drag the number toward 1.0 and hide exactly what it is for.
        """
        scores: List[float] = []

        def walk(node: Any) -> None:
            kids = getattr(node, "children", None)
            if kids:
                for c in kids:
                    walk(c)
                return
            if getattr(node, "is_tombstoned", False):
                return
            cs = getattr(node, "confidence_score", None)
            if isinstance(cs, (int, float)):
                scores.append(float(cs))

        for c in doc.root_containers:
            walk(c)
        return round(sum(scores) / len(scores), 3) if scores else 0.0

    @app.get("/api/v1/documents")
    async def list_documents() -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for job_id, doc in docs_store.items():
            job = job_manager.get_job(job_id)
            node_count = _count_nodes(doc)
            prog = progress_store.get(job_id) or {}
            step, total = prog.get("step", 0), prog.get("total", 0)
            results.append({
                "job_id": job_id,
                "title": doc.title or "Untitled",
                "source_uri": doc.source_uri,
                "status": job.status.value if job else "UNKNOWN",
                "created_at": job.created_at if job else "",
                "updated_at": job.updated_at if job else "",
                "node_count": node_count,
                "page_count": doc.metadata.get("page_count", 0) if doc.metadata else 0,
                # Real numbers: the dashboard used to hardcode 1.0 for both, so
                # every document showed "Avg Conf: 100%" and a progress bar that
                # sat at 0% until it jumped to 100%.
                "confidence_avg": _avg_confidence(doc),
                "progress": (step / total) if total else 0.0,
                "stage": prog.get("stage", ""),
            })
        return results

    @app.get("/api/v1/jobs/{job_id}/result")
    async def get_job_result(job_id: str) -> Dict[str, Any]:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        return _serialize_document(doc)

    @app.get("/api/v1/jobs/{job_id}/pages")
    async def get_page_layout(job_id: str) -> Dict[str, Any]:
        """Per-page render strategy for the editor (RFC 0021 §3).

        The positional-vs-reflow rule lives in the assembler; the editor reads
        the decision from here instead of holding a second implementation that
        could drift out of step with the one that builds the PDF.
        """
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        from src.assembler.page_assembler import page_layout_map
        return {"job_id": job_id, "pages": page_layout_map(doc)}

    def _open_source_pdf(job_id: str, doc: KnowledgeDocument) -> Any:
        """Open the source PDF for a job, supporting both upload:// and sep:// URIs."""
        import pymupdf as fitz
        source_uri = doc.source_uri or ""

        if source_uri.startswith("upload://"):
            filename = source_uri.replace("upload://", "")
            pdf_path = os.path.join(kae_ssd_path, job_id, filename)
            if not os.path.isfile(pdf_path):
                raise HTTPException(status_code=404, detail="Uploaded PDF not found on disk")
            return fitz.open(pdf_path)

        if source_uri.startswith("sep://"):
            parts = source_uri.replace("sep://", "").split("/", 1)
            if len(parts) != 2:
                raise HTTPException(status_code=400, detail="Invalid source_uri")
            provider_id, file_id = parts
            try:
                import asyncio
                sep_provider = _resolve_sep_provider(provider_id)
                loop = asyncio.get_event_loop()
                file_stream = loop.run_until_complete(sep_provider.get_file_stream(file_id))
            except Exception:
                raise HTTPException(status_code=404, detail="Cannot access source file")
            pdf_bytes = file_stream.read()
            return fitz.open(stream=pdf_bytes, filetype="pdf")

        raise HTTPException(status_code=400, detail="Unsupported source URI scheme")

    @app.get("/api/v1/jobs/{job_id}/page-image/{page_num}")
    async def get_page_image(job_id: str, page_num: int) -> Response:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        pdf_doc = _open_source_pdf(job_id, doc)
        if page_num < 0 or page_num >= len(pdf_doc):
            pdf_doc.close()
            raise HTTPException(status_code=400, detail=f"Page {page_num} out of range")
        page = pdf_doc[page_num]
        pix = page.get_pixmap(dpi=100)
        img_bytes = pix.tobytes("jpeg")
        pdf_doc.close()
        return Response(content=img_bytes, media_type="image/jpeg")

    def _resolve_sep_provider(provider_id: str) -> Any:
        """Provider by id, falling back to any local provider (ids change on restart)."""
        try:
            return sep_manager.get_provider(provider_id)
        except KeyError:
            for pid, prov in getattr(sep_manager, "_providers", {}).items():
                return prov
            raise

    def _find_node(doc_obj: KnowledgeDocument, node_id: str) -> Optional[Any]:
        stack: list = list(doc_obj.root_containers)
        while stack:
            n = stack.pop()
            if getattr(n, "id", None) == node_id:
                return n
            stack.extend(getattr(n, "children", []) or [])
        return None

    @app.get("/api/v1/jobs/{job_id}/diagram/{block_id}")
    async def get_diagram_image(job_id: str, block_id: str) -> Response:
        """Render a DiagramBlock's source page region as an image (scan crop)."""
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        node = _find_node(doc, block_id)
        if node is None or not isinstance(node, DiagramBlock):
            raise HTTPException(status_code=404, detail="Diagram not found")
        vl = node.visual_layout
        if vl is None or vl.bounding_box is None:
            raise HTTPException(status_code=400, detail="Diagram has no region")
        import pymupdf as fitz
        pdf_doc = _open_source_pdf(job_id, doc)
        pg = vl.page_or_screen_index
        if pg < 0 or pg >= len(pdf_doc):
            pdf_doc.close()
            raise HTTPException(status_code=400, detail="Page out of range")
        page = pdf_doc[pg]
        pw, ph = page.rect.width, page.rect.height
        bb = vl.bounding_box
        clip = fitz.Rect(bb.x0 * pw, bb.y0 * ph, bb.x1 * pw, bb.y1 * ph)
        pix = page.get_pixmap(clip=clip, dpi=72)
        img_bytes = pix.tobytes("jpeg", jpg_quality=85)
        pdf_doc.close()
        return Response(content=img_bytes, media_type="image/jpeg")

    async def _render_block_png(job_id: str, doc: KnowledgeDocument, node: Any) -> bytes:
        """Render a block's source page region to PNG bytes (for /infer agents)."""
        vl = getattr(node, "visual_layout", None)
        if vl is None or vl.bounding_box is None:
            raise HTTPException(400, "Block has no region")
        import pymupdf as fitz
        pdf_doc = _open_source_pdf(job_id, doc)
        pg = vl.page_or_screen_index
        page = pdf_doc[pg]
        pw, ph = page.rect.width, page.rect.height
        bb = vl.bounding_box
        clip = fitz.Rect(bb.x0 * pw, bb.y0 * ph, bb.x1 * pw, bb.y1 * ph)
        data = page.get_pixmap(clip=clip, dpi=100).tobytes("png")
        pdf_doc.close()
        return data

    def _call_infer(host: str, task: str, image_b64: str) -> Optional[str]:
        """POST an image region to a multimodel/got-ocr agent → recognized text."""
        import urllib.request
        endpoint = "/infer"
        body = json.dumps({"image_b64": image_b64, "task": task}).encode()
        try:
            req = urllib.request.Request(f"{host}{endpoint}", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read()).get("text", "")
        except Exception:
            # Backwards-compat: old GOT-OCR agents expose /ocr instead of /infer.
            try:
                req = urllib.request.Request(f"{host}/ocr", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.loads(r.read()).get("text", "")
            except Exception:
                logging.getLogger(__name__).exception("infer call failed")
                return None

    @app.post("/api/v1/jobs/{job_id}/table/{block_id}/recognize")
    async def recognize_table(job_id: str, block_id: str) -> Dict[str, Any]:
        """Send a table region to the `table`-role agent (GOT-OCR/MinerU) and store
        the returned LaTeX on the TableBlock (used as-is at book assembly)."""
        import base64
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(404, "Document not found")
        node = _find_node(doc, block_id)
        if node is None or not isinstance(node, TableBlock):
            raise HTTPException(404, "Table not found")
        host, _model, _kind = _pick_agent_for_role("table")
        if not host:
            raise HTTPException(503, "No agent with role 'table' available")
        png = await _render_block_png(job_id, doc, node)
        latex = await asyncio.to_thread(_call_infer, host, "table", base64.b64encode(png).decode())
        if not latex:
            raise HTTPException(503, "Table agent failed")
        if not node.metadata:
            node.metadata = {}
        node.metadata["latex"] = latex.strip()
        node.classification_confidence = 0.95
        node.update_confidence()
        _persist_doc(job_id, doc)
        audit_logger.log("TABLE_RECOGNIZED", "agent", {"job_id": job_id, "block_id": block_id})
        return {"status": "recognized", "block_id": block_id, "latex": latex.strip()}

    # --- SemanticChunker & Translation Endpoints ---

    @app.delete("/api/v1/jobs/{job_id}")
    async def delete_job(job_id: str) -> Dict[str, Any]:
        if job_id in docs_store:
            del docs_store[job_id]
        if job_id in graphs_store:
            del graphs_store[job_id]
        json_path = os.path.join(_docs_dir, f"{job_id}.json")
        if os.path.exists(json_path):
            os.remove(json_path)
        ssd_dir = os.path.join(kae_ssd_path, job_id)
        if os.path.isdir(ssd_dir):
            import shutil
            shutil.rmtree(ssd_dir, ignore_errors=True)
        return {"status": "deleted", "job_id": job_id}

    @app.get("/api/v1/jobs/{job_id}/chunks")
    async def get_job_chunks(job_id: str) -> Dict[str, Any]:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        graphs = graphs_store.get(job_id, {})
        rg = graphs.get("rg", ReadingGraph())
        kg = graphs.get("kg", KnowledgeGraph())
        chunker = SemanticChunker()
        chunks = chunker.build_chunks(doc, rg, kg)
        return AIKnowledgeExporter.export_chunks_manifest(chunks)

    class TranslateRequest(BaseModel):
        source_text: str
        target_lang: str = "Russian"
        page_number: Optional[int] = None

    @app.post("/api/v1/jobs/{job_id}/translate")
    async def translate_page(job_id: str, body: TranslateRequest) -> Dict[str, Any]:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        from src.analyzers.llm_refinement import _call_ollama
        prompt = (
            f"Translate the following text to {body.target_lang}. "
            f"Output ONLY the translation, nothing else.\n\n"
            f"{body.source_text}"
        )
        # Route to the first reachable agent configured in the agent manager,
        # using its active model. Lets the user pick a fast host/model in the UI.
        host, model = None, None
        for a in _load_agents_config():
            available, models = _probe_ollama(a["host"])
            if available:
                host = a["host"]
                model = a.get("active_model") or (models[0] if models else None)
                break
        translated = _call_ollama(prompt, host=host, model=model)
        if not translated:
            raise HTTPException(status_code=503, detail="LLM unavailable or timed out")
        audit_logger.log("TRANSLATION_REQUESTED", "api", {
            "job_id": job_id, "page_number": body.page_number,
            "target_lang": body.target_lang,
        })
        return {"translated_text": translated.strip(), "page_number": body.page_number}

    class AssembleRequest(BaseModel):
        target_lang: str = "Russian"
        page_aware: bool = True

    @app.post("/api/v1/jobs/{job_id}/assemble/preview")
    async def assemble_preview(job_id: str) -> Dict[str, Any]:
        """Assemble document from KRM without translation (page-aware layout)."""
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        from src.assembler.translator import _generate_pdf
        output_path = os.path.join(kae_ssd_path, job_id, "preview_pages.pdf")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        def _run():
            return _generate_pdf(doc, "", output_path, job_id, page_aware=True)

        await asyncio.to_thread(_run)
        audit_logger.log("BOOK_ASSEMBLED", "api", {
            "job_id": job_id, "target_lang": "", "mode": "preview",
            "output": output_path,
        })
        return {"status": "completed", "download_url": f"/api/v1/jobs/{job_id}/download/preview"}

    @app.get("/api/v1/jobs/{job_id}/download/preview")
    async def download_preview(job_id: str):
        path = os.path.join(kae_ssd_path, job_id, "preview_pages.pdf")
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="No preview PDF found")
        return FileResponse(path, filename=os.path.basename(path),
                            media_type="application/pdf")

    @app.post("/api/v1/jobs/{job_id}/assemble")
    async def assemble_translated_book(job_id: str, body: AssembleRequest) -> Dict[str, Any]:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        from src.assembler.translator import translate_and_assemble
        loop = asyncio.get_event_loop()
        output_path = os.path.join(kae_ssd_path, job_id, f"translated_{body.target_lang.lower()}.pdf")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        def _run():
            return translate_and_assemble(doc, body.target_lang, output_path, job_id, pyjobkit_bridge, loop)

        await asyncio.to_thread(_run)
        audit_logger.log("BOOK_ASSEMBLED", "api", {
            "job_id": job_id, "target_lang": body.target_lang, "output": output_path,
        })
        return {"status": "completed", "download_url": f"/api/v1/jobs/{job_id}/download/translated"}

    def _pick_agent() -> tuple:
        """First reachable agent + its active model, from the agent manager config."""
        for a in _load_agents_config():
            available, models = _probe_ollama(a["host"])
            if available:
                return a["host"], (a.get("active_model") or (models[0] if models else None))
        return None, None

    class TranslateAllRequest(BaseModel):
        target_lang: str = "Russian"

    @app.post("/api/v1/jobs/{job_id}/translate/start")
    async def translate_all_start(job_id: str, body: TranslateAllRequest) -> Dict[str, Any]:
        """
        Start a background page-by-page translation job. Progress is published to
        the task stream (visible in the task queue); translated segments are stored
        on each block's metadata without mutating the source (RFC 0021 §5.1).
        """
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")

        from src.assembler.translator import _collect_translatable, _get_block_text, _record_translation
        from src.analyzers.llm_refinement import _call_ollama

        blocks: list = []
        for container in doc.root_containers:
            _collect_translatable(container, blocks)

        # Group blocks by physical page for page-by-page progress.
        pages: Dict[int, list] = {}
        for kind, block in blocks:
            vl = getattr(block, "visual_layout", None)
            pg = getattr(vl, "page_or_screen_index", 0) if vl else 0
            pages.setdefault(pg, []).append((kind, block))
        ordered_pages = sorted(pages.keys())
        total_pages = len(ordered_pages)

        host, model, _ = _pick_agent_for_role("translate")
        loop = asyncio.get_event_loop()

        async def _emit(stage: str, step: int) -> None:
            progress_store[job_id] = {"step": step, "total": total_pages, "stage": stage}
            await pyjobkit_bridge.publish_event({
                "event": "job_progress", "job_id": job_id, "job_type": "translate",
                "stage": stage, "progress": (step / total_pages) if total_pages else 1.0,
                "status": "RUNNING",
            })

        def _translate_page(page_blocks: list) -> None:
            for kind, block in page_blocks:
                if kind == "title":
                    original = block.title
                elif kind == "caption":
                    original = block.caption_text
                else:
                    original = _get_block_text(block)
                if not original or len(original.strip()) < 3:
                    continue
                prompt = (
                    f"Translate the following text to {body.target_lang}. "
                    f"Output ONLY the translation, nothing else.\n\n{original}"
                )
                translated = _call_ollama(prompt, host=host, model=model)
                if translated:
                    _record_translation(block, original, translated.strip(), body.target_lang)

        async def _run_job() -> None:
            try:
                for i, pg in enumerate(ordered_pages):
                    await _emit(f"Перевод страницы {i + 1}/{total_pages}", i)
                    await asyncio.to_thread(_translate_page, pages[pg])
                _persist_doc(job_id, doc)
                progress_store[job_id] = {"step": total_pages, "total": total_pages, "stage": "done"}
                await pyjobkit_bridge.publish_event({
                    "event": "job_completed", "job_id": job_id, "job_type": "translate",
                    "progress": 1.0, "status": "COMPLETED",
                })
                audit_logger.log("TRANSLATION_REQUESTED", "api", {
                    "job_id": job_id, "target_lang": body.target_lang, "pages": total_pages,
                })
            except Exception as e:
                logging.getLogger(__name__).exception("Translation job failed for %s", job_id)
                progress_store[job_id] = {"step": 0, "total": total_pages, "stage": "error", "error": str(e)}

        loop.create_task(_run_job())
        return {"status": "started", "total_pages": total_pages, "agent": host, "model": model}

    @app.get("/api/v1/jobs/{job_id}/download/translated")
    async def download_translated(job_id: str):
        import glob
        pattern = os.path.join(kae_ssd_path, job_id, "translated_*.pdf")
        files = glob.glob(pattern)
        if not files:
            raise HTTPException(status_code=404, detail="No translated PDF found")
        return FileResponse(files[0], filename=os.path.basename(files[0]), media_type="application/pdf")

    # --- Agent Configuration ---

    AGENTS_CONFIG_PATH = os.path.join(kae_ssd_path, "agents.json")

    def _load_agents_config() -> List[Dict[str, str]]:
        if os.path.exists(AGENTS_CONFIG_PATH):
            with open(AGENTS_CONFIG_PATH) as f:
                return json.load(f)
        from src.analyzers.llm_refinement import OLLAMA_URL, OLLAMA_MODEL
        # RPi5 + small fast model first (default translation agent); OrangePi 7B
        # is slower on CPU. Users can reorder/retarget via the agent manager.
        defaults = [
            {"name": "RPi5", "host": os.environ.get("LLM_AGENT_URL_2", "http://192.168.88.71:11434"),
             "active_model": "llama3.1:8b", "kind": "ollama", "roles": ["translate", "refine"]},
            {"name": "OrangePi", "host": OLLAMA_URL, "active_model": OLLAMA_MODEL,
             "kind": "ollama", "roles": []},
        ]
        _save_agents_config(defaults)
        return defaults

    def _save_agents_config(agents: List[Dict[str, str]]) -> None:
        with open(AGENTS_CONFIG_PATH, "w") as f:
            json.dump(agents, f, indent=2)

    def _probe_ollama(host: str) -> tuple:
        import urllib.request
        try:
            req = urllib.request.Request(f"{host}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                return True, [m["name"] for m in data.get("models", [])]
        except Exception:
            return False, []

    def _probe_agent(host: str, kind: str) -> tuple:
        """Health-check an agent.
        Returns (available, models, extra) where extra is any additional health
        payload (for kind=managed: {runner, runner_url, queue_depth}).
        """
        if kind in ("got-ocr", "multimodel", "managed"):
            import urllib.request
            try:
                req = urllib.request.Request(f"{host}/health")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    tasks = data.get("tasks") or [data.get("model", kind)]
                    extra = {}
                    if kind == "managed":
                        # Surface RFC 0022 §4.1 fields for UI (Stage 6).
                        extra = {
                            "runner": data.get("runner"),
                            "runner_url": data.get("runner_url"),
                            "queue_depth": data.get("queue_depth"),
                        }
                    return True, tasks, extra
            except Exception:
                return False, [], {}
        ok, models = _probe_ollama(host)
        return ok, models, {}

    # --- Skills API (RFC 0006) ---

    _skills_runner_instance: Optional[Any] = None

    def _get_skills_runner() -> Any:
        nonlocal _skills_runner_instance
        if _skills_runner_instance is None:
            from src.skills.runner import SkillsRunner
            from pathlib import Path
            runner = SkillsRunner()
            skills_dir = Path("skills")
            if skills_dir.exists():
                runner.load_directory(skills_dir)
        _skills_runner_instance = runner
        return _skills_runner_instance

    @app.get("/api/v1/skills")
    async def list_skills() -> List[Dict[str, Any]]:
        runner = _get_skills_runner()
        result = []
        for name, pack in runner.packs.items():
            result.append({
                "name": pack.name,
                "version": pack.version,
                "description": pack.metadata.get("description", ""),
                "apply_when": pack.apply_when,
                "steps": pack.steps,
                "disabled": pack.disabled,
            })
        return result

    @app.post("/api/v1/skills/{skill_name}/activate")
    async def activate_skill(skill_name: str, job_id: str) -> Dict[str, Any]:
        runner = _get_skills_runner()
        pack = runner.packs.get(skill_name)
        if pack is None:
            return {"error": f"Skill pack '{skill_name}' not found"}
        if job_id not in jobs:
            return {"error": f"Job '{job_id}' not found"}
        job = jobs[job_id]
        doc = job.get("document")
        if doc is None:
            return {"error": "Job has no document"}
        job.setdefault("active_skills", []).append(skill_name)
        return {
            "status": "activated",
            "skill": skill_name,
            "job_id": job_id,
            "pipeline_steps": len(runner.build_pipeline(pack)),
        }

    @app.get("/api/v1/agents/config")
    async def get_agents_config() -> Dict[str, Any]:
        saved = _load_agents_config()
        result = []
        for h in saved:
            kind = h.get("kind", "ollama")
            available, models, extra = _probe_agent(h["host"], kind)
            active = h.get("active_model", "")
            if available and active and active not in models:
                active = models[0] if models else ""
            entry = {
                "name": h["name"],
                "host": h["host"],
                "kind": kind,
                "roles": h.get("roles", []),
                "models": models,
                "active_model": active,
                "available": available,
            }
            entry.update({k: v for k, v in extra.items() if v is not None})
            result.append(entry)
        return {"agents": result}

    class AgentCreateRequest(BaseModel):
        name: str
        host: str
        active_model: str = ""
        kind: str = "ollama"
        roles: List[str] = Field(default_factory=list)

    @app.post("/api/v1/agents/config")
    async def add_agent(body: AgentCreateRequest) -> Dict[str, Any]:
        agents = _load_agents_config()
        if any(a["host"] == body.host for a in agents):
            raise HTTPException(400, "Agent with this host already exists")
        agents.append({"name": body.name, "host": body.host,
                       "active_model": body.active_model, "kind": body.kind,
                       "roles": body.roles})
        _save_agents_config(agents)
        return {"status": "added", "name": body.name}

    @app.put("/api/v1/agents/config")
    async def update_agent(body: AgentCreateRequest) -> Dict[str, Any]:
        agents = _load_agents_config()
        for a in agents:
            if a["host"] == body.host:
                a["name"] = body.name
                a["active_model"] = body.active_model
                a["roles"] = body.roles
                _save_agents_config(agents)
                return {"status": "updated", "name": body.name}
        raise HTTPException(404, "Agent not found")

    def _pick_agent_for_role(role: str) -> tuple:
        """First reachable agent that declares `role`, else any reachable ollama.
        Returns (host, model, kind)."""
        cfg = _load_agents_config()
        for a in cfg:
            if role in (a.get("roles") or []):
                kind = a.get("kind", "ollama")
                available, models, extra = _probe_agent(a["host"], kind)
                # For managed: only route when the underlying Runner is UP.
                if available and (kind != "managed" or extra.get("runner") == "up"):
                    model = a.get("active_model") or (models[0] if models else None)
                    return a["host"], model, kind
        # Fallback: any reachable ollama agent (keeps old behaviour working).
        for a in cfg:
            if a.get("kind", "ollama") == "ollama":
                available, models = _probe_ollama(a["host"])
                if available:
                    return a["host"], (a.get("active_model") or (models[0] if models else None)), "ollama"
        return None, None, "ollama"

    @app.delete("/api/v1/agents/{host:path}")
    async def delete_agent(host: str) -> Dict[str, Any]:
        agents = _load_agents_config()
        new = [a for a in agents if a["host"] != host]
        if len(new) == len(agents):
            raise HTTPException(404, "Agent not found")
        _save_agents_config(new)
        return {"status": "deleted"}

    # --- Node Refinement (HITL / LLM Agent) ---

    class RefineRequest(BaseModel):
        node_id: str
        mode: str  # 'agent' | 'manual'
        patch: Optional[Dict[str, Any]] = None

    @app.post("/api/v1/jobs/{job_id}/refine")
    async def refine_node(job_id: str, body: RefineRequest) -> Dict[str, Any]:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")

        def find_node(containers, node_id):
            for c in containers:
                if getattr(c, 'id', None) == node_id:
                    return c
                for child in getattr(c, 'children', []):
                    if getattr(child, 'id', None) == node_id:
                        return child
                found = find_node(getattr(c, 'children', []), node_id)
                if found:
                    return found
            return None

        target = find_node(doc.root_containers, body.node_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Node not found")

        if body.mode == 'manual' and body.patch:
            if 'type' in body.patch and hasattr(target, 'block_type'):
                target.block_type = body.patch['type']
            if 'text' in body.patch:
                if hasattr(target, 'title'):
                    target.title = body.patch['text']
            target.classification_confidence = 1.0
            target.extraction_confidence = 1.0
            _persist_doc(job_id, doc)
            audit_logger.log("HITL_CORRECTION", "user", {
                "job_id": job_id, "node_id": body.node_id, "mode": "manual",
            })
            return {"status": "updated", "node_id": body.node_id}

        if body.mode == 'agent':
            from src.analyzers.llm_refinement import _call_ollama, VALID_TYPES, OLLAMA_MODEL
            import re as _re
            text_parts = []
            if hasattr(target, 'inlines'):
                for inline in (target.inlines or []):
                    for span in getattr(inline, 'spans', []):
                        if hasattr(span, 'text'):
                            text_parts.append(span.text)
            elif hasattr(target, 'title'):
                text_parts.append(target.title or '')
            node_text = " ".join(text_parts).strip()
            if not node_text:
                return {"status": "error", "detail": "Node has no text"}

            snippet = node_text[:200]
            prompt = (
                f'Classify this text block from a book. Reply with ONLY one word from: '
                f'paragraph, toc_entry, caption, heading, code, formula, list_item, table_cell.\n\n'
                f'Text: "{snippet}"\n\nType:'
            )
            response = _call_ollama(prompt)
            if not response:
                return {"status": "error", "detail": "LLM unavailable or timed out"}

            block_type = response.strip().lower().replace('"', '').replace("'", "").split()[0] if response.strip() else ""
            block_type = block_type.rstrip(".,;:")
            if block_type not in VALID_TYPES:
                for vt in VALID_TYPES:
                    if vt in response.lower():
                        block_type = vt
                        break

            if block_type in VALID_TYPES:
                target.classification_confidence = 0.85
                target.update_confidence()
                if not target.metadata:
                    target.metadata = {}
                target.metadata["llm_suggested_type"] = block_type
                target.metadata["llm_model"] = OLLAMA_MODEL
                _persist_doc(job_id, doc)

            audit_logger.log("HITL_CORRECTION", "llm_agent", {
                "job_id": job_id, "node_id": body.node_id, "mode": "agent",
                "llm_type": block_type, "raw": response.strip()[:100],
            })
            return {
                "status": "refined",
                "node_id": body.node_id,
                "llm_result": {"type": block_type, "confidence": target.confidence_score},
                "confidence": target.confidence_score,
            }

        raise HTTPException(status_code=400, detail=f"Unknown mode: {body.mode}")

    @app.post("/api/v1/jobs/{job_id}/refine-page/{page}")
    async def refine_page(job_id: str, page: int) -> Dict[str, Any]:
        """
        Page-level agent refinement: the agent looks at every block on one page at
        once (with its text and page image) and classifies the undetermined ones.
        More context than per-block refine, so it fixes what single blocks miss.
        """
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        from src.analyzers.llm_refinement import _call_ollama, VALID_TYPES

        def _text(n: Any) -> str:
            if hasattr(n, "inlines"):
                return " ".join(s.text for i in (n.inlines or [])
                                for s in getattr(i, "spans", []) if hasattr(s, "text")).strip()
            return (getattr(n, "title", "") or "").strip()

        # Collect non-tombstoned leaf blocks on this page.
        blocks: List[Any] = []
        def walk(nodes: list) -> None:  # type: ignore[type-arg]
            for n in nodes:
                if getattr(n, "is_tombstoned", False):
                    continue
                vl = getattr(n, "visual_layout", None)
                pg = getattr(vl, "page_or_screen_index", None) if vl else None
                if pg == page and not isinstance(n, ContainerUnit) and _text(n):
                    blocks.append(n)
                if getattr(n, "children", None):
                    walk(n.children)
        for c in doc.root_containers:
            walk([c])

        if not blocks:
            return {"status": "empty", "page": page, "refined": 0}

        listing = "\n".join(f'{i+1}. "{_text(b)[:120]}"' for i, b in enumerate(blocks))
        prompt = (
            "This image is one page of a scanned book. Along with it you get the "
            "text blocks extracted from the page, in reading order.\n\n"
            f"BLOCKS:\n{listing}\n\n"
            "First decide the PAGE ROLE: title, toc, table, diagram, figure, code, "
            "formula, text. Then classify EACH block: paragraph, heading, toc_entry, "
            "caption, code, formula, list_item, table_cell, title, label.\n"
            'Reply with ONLY JSON: {"role":"...","blocks":[{"n":1,"type":"..."},...]}. '
            "No prose, no code fences."
        )

        # Prefer a vision agent (sees the page image); fall back to text-only ollama.
        from src.agents.router import pick as _pick_role, call_infer as _call_agent
        from src.analyzers.page_agent import _resolve_source_path
        host_v, model_v, _ = _pick_role("vision")
        model = model_v
        resp: Optional[str] = None
        if host_v:
            try:
                import pymupdf as fitz
                pdf_path = _resolve_source_path(doc)
                if pdf_path:
                    pdf = fitz.open(pdf_path)
                    png = pdf[page].get_pixmap(dpi=100).tobytes("png")
                    pdf.close()
                    resp = await asyncio.to_thread(_call_agent, host_v, "vision", png, prompt)
            except Exception:
                logging.getLogger(__name__).exception("vision refine-page failed; falling back")
        if not resp:
            host, model = _pick_agent()
            resp = _call_ollama(prompt, host=host, model=model)
        if not resp:
            raise HTTPException(status_code=503, detail="Agent unavailable or timed out")

        import re as _re, json as _json
        role = "text"
        types: Dict[int, str] = {}
        m = _re.search(r"\{.*\}", resp, _re.DOTALL)
        if m:
            try:
                data = _json.loads(m.group())
                role = str(data.get("role", "text")).lower().strip()
                for item in data.get("blocks", []):
                    idx = int(item.get("n", 0)) - 1
                    bt = str(item.get("type", "")).lower().strip()
                    if 0 <= idx < len(blocks) and bt in VALID_TYPES:
                        types[idx] = bt
            except Exception:
                pass

        rebuilt = None
        # Rebuild the page structure per the agent's role decision (RFC 0001 §2.4:
        # absorbed blocks are tombstoned, not deleted).
        if role in ("title", "diagram", "table", "toc"):
            rebuilt = _rebuild_page(doc, blocks, role, page, types)

        refined = 0
        for idx, bt in types.items():
            b = blocks[idx]
            if getattr(b, "is_tombstoned", False):
                continue
            b.classification_confidence = 0.85
            b.update_confidence()
            if not b.metadata:
                b.metadata = {}
            b.metadata["llm_suggested_type"] = bt
            b.metadata["llm_model"] = model or ""
            refined += 1

        _persist_doc(job_id, doc)
        audit_logger.log("HITL_CORRECTION", "llm_agent", {
            "job_id": job_id, "mode": "page", "page": page,
            "role": role, "refined": refined, "rebuilt": rebuilt,
        })
        return {"status": "refined", "page": page, "role": role,
                "blocks": len(blocks), "refined": refined, "rebuilt": rebuilt}

    # TOC entry prefix: "Section 2", "Chapter III", "Appendix A", "1.2.3", "2.1"
    import re as _re_toc
    _RE_TOC_BOUNDARY = _re_toc.compile(
        r"\s+(?=(?:Section|Chapter|Appendix|Part|Глава|Раздел|Приложение)\b|\d+\.\d)",
        _re_toc.IGNORECASE,
    )
    _RE_TOC_ENTRY = _re_toc.compile(
        r"^(?P<kind>Section|Chapter|Appendix|Part|Глава|Раздел|Приложение)?\s*"
        r"(?P<num>[A-Z0-9]+(?:\.\d+)*)?\s*"
        r"(?P<title>.*?)"
        r"(?:\s*[.\s]{2,}\s*|\s+)(?P<page>\d{1,4}|[ivxlcdm]+|[IVXLCDM]+)?\s*$",
        _re_toc.IGNORECASE,
    )

    def _split_toc_line(text: str) -> List[str]:
        """Split OCR-glued TOC lines at prefix boundaries ("Section 2 X 2.1 Y…")."""
        parts = _RE_TOC_BOUNDARY.split(text.strip())
        return [p.strip() for p in parts if p.strip()]

    def _parse_toc_entry(text: str) -> Dict[str, Any]:
        """Extract {level, number, title, target_page, display} from one entry."""
        t = text.strip()
        m = _RE_TOC_ENTRY.match(t)
        if not m:
            return {"level": 1, "number": None, "title": t, "target_page": None, "display": t}
        kind = (m.group("kind") or "").strip()
        num = (m.group("num") or "").strip()
        title = (m.group("title") or "").strip(" .·—-").strip()
        page = m.group("page")
        try:
            page_num = int(page) if page and page.isdigit() else None
        except Exception:
            page_num = None
        level = 1 if not num or "." not in num else 1 + num.count(".")
        prefix = " ".join(x for x in (kind, num) if x).strip()
        display = f"{prefix}. {title}" if prefix and title else (prefix or title or t)
        if page_num is not None:
            display = f"{display} … {page_num}"
        return {"level": level, "number": prefix or None, "title": title,
                "target_page": page_num, "display": display}

    def _rebuild_page(doc: KnowledgeDocument, blocks: List[Any], role: str, page: int,
                      types: Optional[Dict[int, str]] = None) -> Optional[str]:
        """Reassemble a page's blocks into a title / diagram / table / toc structure."""
        from src.krm.models import (TitlePageBlock, DiagramBlock, TextLineInline,
                                     StyledTextSpan, VisualLayout, NormalizedRect)

        def _text(n: Any) -> str:
            if hasattr(n, "inlines"):
                return " ".join(s.text for i in (n.inlines or [])
                                for s in getattr(i, "spans", []) if hasattr(s, "text")).strip()
            return (getattr(n, "title", "") or "").strip()

        # Locate the parent container + insertion index of the first block.
        parent, first_idx = None, 0
        for c in doc.root_containers:
            stack = [(c, None)]
            while stack:
                node, par = stack.pop()
                if node is blocks[0] and par is not None:
                    parent = par
                    first_idx = par.children.index(node)
                for ch in getattr(node, "children", []) or []:
                    stack.append((ch, node))
        if parent is None:
            parent = doc.root_containers[0]

        region = NormalizedRect(0.0, 0.0, 1.0, 1.0)
        bbs = [getattr(getattr(b, "visual_layout", None), "bounding_box", None) for b in blocks]
        bbs = [b for b in bbs if b]
        if bbs:
            region = NormalizedRect(
                max(0.0, min(b.x0 for b in bbs) - 0.02), max(0.0, min(b.y0 for b in bbs) - 0.02),
                min(1.0, max(b.x1 for b in bbs) + 0.05), min(1.0, max(b.y1 for b in bbs) + 0.03))

        if role == "toc":
            # Skip if this page's parent already holds a TOC container — don't
            # nest a second "Оглавление" on repeat clicks.
            if getattr(parent, "semantic_type", "") == "toc":
                return "toc:already"
            # A TOC is a LIST, not paragraphs. Split glued OCR lines into entries
            # (e.g. "Section 2 X 2.1 Y 2.2 Z" → three items) and parse each entry
            # into level/number/title/page for the assembler.
            entries: List[Dict[str, Any]] = []
            for b in blocks:
                txt = _text(b)
                if not txt:
                    continue
                for e in _split_toc_line(txt):
                    parsed = _parse_toc_entry(e)
                    entries.append(parsed)

            new = ContainerUnit(title="Оглавление", level=2, semantic_type="toc")
            new.visual_layout = VisualLayout(bounding_box=region, page_or_screen_index=page)
            new.extraction_confidence = 0.95
            new.classification_confidence = 0.95
            new.confidence_score = 0.95
            for e in entries:
                target_page = e["target_page"]
                zero_based = target_page - 1 if isinstance(target_page, int) else None
                item = TocEntryBlock(
                    entry_text=e["display"],
                    chapter_number=e["number"],
                    target_page=zero_based,
                    visual_layout=VisualLayout(bounding_box=region, page_or_screen_index=page),
                    extraction_confidence=0.95,
                    classification_confidence=0.95,
                    confidence_score=0.95,
                )
                item.metadata = {
                    "llm_suggested_type": "toc_entry",
                    "llm_source": "PageAgent",
                    "toc": {"level": e["level"], "title": e["title"]},
                }
                new.children.append(item)
            parent.children.insert(min(first_idx, len(parent.children)), new)
            for b in blocks:
                b.is_tombstoned = True
                if not b.metadata:
                    b.metadata = {}
                b.metadata["tombstone_reason"] = f"page_agent_rebuilt:toc:{new.id}"
            return f"toc:{new.id}"
        if role == "title":
            new = TitlePageBlock(page_role="title")
            new.inlines = [TextLineInline(spans=[StyledTextSpan(text="\n".join(_text(b) for b in blocks if _text(b)))])]
            new.visual_layout = VisualLayout(bounding_box=region, page_or_screen_index=page)
        elif role == "diagram":
            new = DiagramBlock(
                labels=[{"text": _text(b), **{k: getattr(bb, k) for k in ("x0", "y0", "x1", "y1")}}
                        for b, bb in zip(blocks, bbs) if _text(b)],
                visual_layout=VisualLayout(bounding_box=region, page_or_screen_index=page))
        else:  # table — mark cells; spatial table build stays with TableDetector
            for b in blocks:
                if not b.metadata:
                    b.metadata = {}
                b.metadata["llm_suggested_type"] = "table_cell"
            return "table_cells_marked"

        new.extraction_confidence = 0.9
        new.classification_confidence = 0.9
        new.confidence_score = 0.9
        parent.children.insert(min(first_idx, len(parent.children)), new)
        for b in blocks:
            b.is_tombstoned = True
            if not b.metadata:
                b.metadata = {}
            b.metadata["tombstone_reason"] = f"page_agent_rebuilt:{role}:{new.id}"
        return f"{role}:{new.id}"

    # --- PyJobKit Reactive SSE and WebSocket Endpoints ---

    @app.get("/api/v1/jobs/stream")
    async def stream_jobs() -> StreamingResponse:
        """
        Server-Sent Events (SSE) endpoint broadcasting all PyJobKit job status and progress events.
        """
        queue = pyjobkit_bridge.subscribe_global_events()

        async def event_generator() -> AsyncGenerator[str, None]:
            yield ": connected\n\n"
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.5)
                        yield f"data: {json.dumps(event)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                pass
            finally:
                pyjobkit_bridge.unsubscribe_global_events(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.websocket("/api/v1/ws/jobs/{job_id}")
    async def websocket_job_status(websocket: WebSocket, job_id: str) -> None:
        """
        WebSocket endpoint tracking real-time status and progress events for a specific PyJobKit job_id.
        """
        await websocket.accept()
        queue = pyjobkit_bridge.subscribe_job_events(job_id)

        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
                if event.get("event") in ("job_completed", "job_failed"):
                    break
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            pyjobkit_bridge.unsubscribe_job_events(job_id, queue)

    return app


# Default singleton app instance
app = create_app()
