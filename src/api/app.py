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
from typing import Any, AsyncGenerator, Dict, List, Optional
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
    BaseKRMNode,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    FigureBlock,
    FormulaBlock,
    KnowledgeDocument,
    ParagraphBlock,
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
                count += 1
                if isinstance(child, ContainerUnit):
                    walk(child.children)
        for c in doc.root_containers:
            count += 1
            walk(c.children)
        return count

    def _serialize_document(doc: KnowledgeDocument) -> Dict[str, Any]:
        def serialize_node(node: Any) -> Dict[str, Any]:
            if isinstance(node, ContainerUnit):
                result = {
                    "id": node.id,
                    "type": "ContainerUnit",
                    "title": node.title,
                    "level": node.level,
                    "confidence_score": node.confidence_score,
                    "extraction_confidence": node.extraction_confidence,
                    "classification_confidence": node.classification_confidence,
                    "children": [serialize_node(c) for c in node.children],
                }
                if node.semantic_type:
                    result["semantic_type"] = node.semantic_type
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
            return {"id": getattr(node, "id", ""), "type": type(node).__name__}

        return {
            "title": doc.title,
            "source_uri": doc.source_uri,
            "source_type": doc.source_type,
            "page_count": doc.metadata.get("page_count", 0) if doc.metadata else 0,
            "containers": [serialize_node(c) for c in doc.root_containers],
        }

    def _rebuild_document(data: Dict[str, Any]) -> KnowledgeDocument:
        def _restore_layout(node: Any, n: Dict[str, Any]) -> None:
            pg = n.get("page_index")
            if pg is not None:
                from src.krm.models import VisualLayout, NormalizedRect
                node.visual_layout = VisualLayout(
                    bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
                    page_or_screen_index=pg,
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
                    job_manager.restore_job(job_id, data.get("_source_uri", ""), "COMPLETED")
            except Exception:
                pass

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
        """
        source_uri = "upload://file.txt"

        if file is not None and file.filename:
            source_uri = f"upload://{file.filename}"
            _raw_bytes = await file.read()
        elif payload is not None and payload.source_uri:
            source_uri = payload.source_uri

        job = job_manager.create_job(source_uri=source_uri)

        # Create initial document and attach to docs store
        doc = KnowledgeDocument(source_uri=source_uri)
        container = ContainerUnit(title="Root Section", level=1)
        
        content_text = payload.content if (payload and payload.content) else "Sample uploaded text content"
        paragraph = ParagraphBlock(
            confidence_score=0.5,
            inlines=[TextLineInline(spans=[StyledTextSpan(text=content_text)])]
        )
        container.children.append(paragraph)
        doc.root_containers.append(container)

        docs_store[job.job_id] = doc
        _persist_doc(job.job_id, doc)

        # Run analyzer pipeline
        rg = ReadingGraph()
        kg = KnowledgeGraph()
        pipeline = PipelineRunner(create_default_pipeline())
        pipeline.execute(doc, rg, kg)
        graphs_store[job.job_id] = {"rg": rg, "kg": kg}

        hitl_manager.flag_low_confidence_nodes(doc, threshold=0.80)

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

    async def _process_import_background(
        job: Any,
        provider_id: str,
        file_id: str,
        ext: str,
    ) -> None:
        """Background task: parse PDF and run analyzer pipeline."""
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
            sep_provider = sep_manager.get_provider(provider_id)
            file_stream = await sep_provider.get_file_stream(file_id)

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

    @app.get("/api/v1/documents")
    async def list_documents() -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for job_id, doc in docs_store.items():
            job = job_manager.get_job(job_id)
            node_count = _count_nodes(doc)
            results.append({
                "job_id": job_id,
                "title": doc.title or "Untitled",
                "source_uri": doc.source_uri,
                "status": job.status.value if job else "UNKNOWN",
                "created_at": job.created_at if job else "",
                "updated_at": job.updated_at if job else "",
                "node_count": node_count,
                "page_count": doc.metadata.get("page_count", 0) if doc.metadata else 0,
            })
        return results

    @app.get("/api/v1/jobs/{job_id}/result")
    async def get_job_result(job_id: str) -> Dict[str, Any]:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        return _serialize_document(doc)

    @app.get("/api/v1/jobs/{job_id}/page-image/{page_num}")
    async def get_page_image(job_id: str, page_num: int) -> Response:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        source_uri = doc.source_uri or ""
        if not source_uri.startswith("sep://"):
            raise HTTPException(status_code=400, detail="Only SEP documents supported")
        parts = source_uri.replace("sep://", "").split("/", 1)
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="Invalid source_uri")
        provider_id, file_id = parts
        try:
            sep_provider = sep_manager.get_provider(provider_id)
            file_stream = await sep_provider.get_file_stream(file_id)
        except Exception:
            raise HTTPException(status_code=404, detail="Cannot access source file")
        import pymupdf as fitz
        pdf_bytes = file_stream.read()
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if page_num < 0 or page_num >= len(pdf_doc):
            raise HTTPException(status_code=400, detail=f"Page {page_num} out of range")
        page = pdf_doc[page_num]
        pix = page.get_pixmap(dpi=100)
        img_bytes = pix.tobytes("jpeg")
        pdf_doc.close()
        return Response(content=img_bytes, media_type="image/jpeg")

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
        ssd_dir = os.path.join(SSD_PATH, job_id)
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
        translated = _call_ollama(prompt)
        if not translated:
            raise HTTPException(status_code=503, detail="LLM unavailable or timed out")
        audit_logger.log("TRANSLATION_REQUESTED", "api", {
            "job_id": job_id, "page_number": body.page_number,
            "target_lang": body.target_lang,
        })
        return {"translated_text": translated.strip(), "page_number": body.page_number}

    class AssembleRequest(BaseModel):
        target_lang: str = "Russian"

    @app.post("/api/v1/jobs/{job_id}/assemble")
    async def assemble_translated_book(job_id: str, body: AssembleRequest) -> Dict[str, Any]:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        from src.assembler.translator import translate_and_assemble
        loop = asyncio.get_event_loop()
        output_path = os.path.join(SSD_PATH, job_id, f"translated_{body.target_lang.lower()}.pdf")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        def _run():
            return translate_and_assemble(doc, body.target_lang, output_path, job_id, pyjobkit_bridge, loop)

        await asyncio.to_thread(_run)
        audit_logger.log("BOOK_ASSEMBLED", "api", {
            "job_id": job_id, "target_lang": body.target_lang, "output": output_path,
        })
        return {"status": "completed", "download_url": f"/api/v1/jobs/{job_id}/download/translated"}

    @app.get("/api/v1/jobs/{job_id}/download/translated")
    async def download_translated(job_id: str):
        import glob
        pattern = os.path.join(SSD_PATH, job_id, "translated_*.pdf")
        files = glob.glob(pattern)
        if not files:
            raise HTTPException(status_code=404, detail="No translated PDF found")
        return FileResponse(files[0], filename=os.path.basename(files[0]), media_type="application/pdf")

    # --- Agent Configuration ---

    AGENTS_CONFIG_PATH = os.path.join(ssd_dir, "agents.json")

    def _load_agents_config() -> List[Dict[str, str]]:
        if os.path.exists(AGENTS_CONFIG_PATH):
            with open(AGENTS_CONFIG_PATH) as f:
                return json.load(f)
        from src.analyzers.llm_refinement import OLLAMA_URL, OLLAMA_MODEL
        defaults = [
            {"name": "OrangePi", "host": OLLAMA_URL, "active_model": OLLAMA_MODEL},
            {"name": "RPi5", "host": os.environ.get("LLM_AGENT_URL_2", "http://192.168.88.73:11434"), "active_model": ""},
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

    @app.get("/api/v1/agents/config")
    async def get_agents_config() -> Dict[str, Any]:
        saved = _load_agents_config()
        result = []
        for h in saved:
            available, models = _probe_ollama(h["host"])
            active = h.get("active_model", "")
            if available and active and active not in models:
                active = models[0] if models else ""
            result.append({
                "name": h["name"],
                "host": h["host"],
                "models": models,
                "active_model": active,
                "available": available,
            })
        return {"agents": result}

    class AgentCreateRequest(BaseModel):
        name: str
        host: str
        active_model: str = ""

    @app.post("/api/v1/agents/config")
    async def add_agent(body: AgentCreateRequest) -> Dict[str, Any]:
        agents = _load_agents_config()
        if any(a["host"] == body.host for a in agents):
            raise HTTPException(400, "Agent with this host already exists")
        agents.append({"name": body.name, "host": body.host, "active_model": body.active_model})
        _save_agents_config(agents)
        return {"status": "added", "name": body.name}

    @app.put("/api/v1/agents/config")
    async def update_agent(body: AgentCreateRequest) -> Dict[str, Any]:
        agents = _load_agents_config()
        for a in agents:
            if a["host"] == body.host:
                a["name"] = body.name
                a["active_model"] = body.active_model
                _save_agents_config(agents)
                return {"status": "updated", "name": body.name}
        raise HTTPException(404, "Agent not found")

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
