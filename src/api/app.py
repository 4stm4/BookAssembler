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
import os
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

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
from fastapi.responses import StreamingResponse
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
                return {
                    "id": node.id,
                    "type": "ContainerUnit",
                    "title": node.title,
                    "level": node.level,
                    "confidence_score": node.confidence_score,
                    "children": [serialize_node(c) for c in node.children],
                }
            elif isinstance(node, ParagraphBlock):
                text_parts = []
                for inline in (node.inlines or []):
                    if hasattr(inline, "spans"):
                        for span in inline.spans:
                            if hasattr(span, "text"):
                                text_parts.append(span.text)
                return {
                    "id": node.id,
                    "type": "ParagraphBlock",
                    "text": " ".join(text_parts),
                    "confidence_score": node.confidence_score,
                }
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
                return {
                    "id": node.id,
                    "type": "TableBlock",
                    "rows": rows,
                    "confidence_score": node.confidence_score,
                }
            return {"id": getattr(node, "id", ""), "type": type(node).__name__}

        return {
            "title": doc.title,
            "source_uri": doc.source_uri,
            "source_type": doc.source_type,
            "page_count": doc.metadata.get("page_count", 0) if doc.metadata else 0,
            "containers": [serialize_node(c) for c in doc.root_containers],
        }

    def _rebuild_document(data: Dict[str, Any]) -> KnowledgeDocument:
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
                return p
            elif t == "CodeBlock":
                cb = CodeBlock(
                    code_text=n.get("text", ""),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                cb.id = n.get("id", cb.id)
                return cb
            elif t == "FigureBlock":
                fb = FigureBlock(
                    image_uri=n.get("image_uri", ""),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                fb.id = n.get("id", fb.id)
                return fb
            elif t == "FormulaBlock":
                fm = FormulaBlock(
                    latex_expression=n.get("text", ""),
                    confidence_score=n.get("confidence_score", 1.0),
                )
                fm.id = n.get("id", fm.id)
                return fm
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

        # Parse imported file through adapter registry
        ext = os.path.splitext(body.file_id)[1].lstrip(".")
        adapter = adapter_registry.get_adapter_for_extension(ext)
        if adapter:
            try:
                sep_provider = sep_manager.get_provider(provider_id)
                file_stream = await sep_provider.get_file_stream(body.file_id)
                loop = asyncio.get_event_loop()
                doc = await loop.run_in_executor(
                    None, adapter.parse, file_stream, job.source_uri
                )
                docs_store[job.job_id] = doc
                _persist_doc(job.job_id, doc)

                rg = ReadingGraph()
                kg = KnowledgeGraph()
                pipeline = PipelineRunner(create_default_pipeline())
                pipeline.execute(doc, rg, kg)
                graphs_store[job.job_id] = {"rg": rg, "kg": kg}
                hitl_manager.flag_low_confidence_nodes(doc, threshold=0.80)

                audit_logger.log("DOCUMENT_IMPORTED", "system", {
                    "job_id": job.job_id, "source_uri": job.source_uri,
                })
                audit_logger.log("PIPELINE_EXECUTED", "system", {
                    "job_id": job.job_id,
                    "analyzers": [a.manifest.name for a in create_default_pipeline()],
                })

                job_manager.update_status(job.job_id, JobStatus.COMPLETED)
            except Exception as parse_err:
                doc = KnowledgeDocument(source_uri=job.source_uri)
                container = ContainerUnit(title="Parse Error", level=1)
                container.children.append(
                    ParagraphBlock(
                        inlines=[TextLineInline(spans=[StyledTextSpan(text=f"Parse error: {parse_err}")])],
                    )
                )
                doc.root_containers.append(container)
                docs_store[job.job_id] = doc
                job_manager.update_status(job.job_id, JobStatus.FAILED)
        else:
            doc = KnowledgeDocument(source_uri=job.source_uri)
            container = ContainerUnit(title="Unsupported Format", level=1)
            container.children.append(
                ParagraphBlock(
                    inlines=[TextLineInline(spans=[StyledTextSpan(text=f"No adapter for .{ext}")])],
                )
            )
            doc.root_containers.append(container)
            docs_store[job.job_id] = doc

        return SEPImportResponse(
            job_id=job.job_id,
            status=job.status.value,
            source_uri=job.source_uri,
        )

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

    # --- SemanticChunker & Translation Endpoints ---

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
        page_number: int
        source_text: str

    @app.post("/api/v1/jobs/{job_id}/translate")
    async def translate_page(job_id: str, body: TranslateRequest) -> Dict[str, Any]:
        doc = docs_store.get(job_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"No document for job '{job_id}'")
        audit_logger.log("TRANSLATION_REQUESTED", "api", {
            "job_id": job_id, "page_number": body.page_number,
        })
        translated = f"[Translation pending — connect LLM API]\n\n{body.source_text}"
        return {"translated_text": translated, "page_number": body.page_number}

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
