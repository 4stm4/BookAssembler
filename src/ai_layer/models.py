"""
Models for AI Knowledge Layer and Semantic Chunking in Knowledge Assembly Engine (KAE).

Defines ChunkBreadcrumbs, AIContextChunk, and RAGGraphExport data structures
according to RFC 0007 (docs/architecture/0007-ai-layer.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, uuid)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class ChunkBreadcrumbs:
    """
    Hierarchical context header detailing document title, container hierarchy path, and page numbers.
    """
    document_title: str
    container_path: List[str] = field(default_factory=list)
    page_numbers: List[int] = field(default_factory=list)

    def to_header_string(self) -> str:
        """
        Formats breadcrumbs as a standardized context header string.
        """
        path_str = " > ".join(self.container_path)
        if path_str:
            return f"[Context: {self.document_title} | {path_str} | Pages: {self.page_numbers}]"
        return f"[Context: {self.document_title} | Pages: {self.page_numbers}]"


@dataclass
class AIContextChunk:
    """
    Semantic knowledge chunk ready for vector embedding, fine-tuning, and RAG ingestion.
    """
    chunk_id: str = field(default_factory=lambda: str(uuid4()))
    source_krm_ids: List[str] = field(default_factory=list)

    text_content: str = ""
    contextual_text: str = ""

    chunk_type: str = "narrative"  # 'narrative', 'code', 'table', 'figure', 'formula', 'instruction', 'definition', 'warning'
    language_or_arch: Optional[str] = None

    parent_container_id: str = ""
    previous_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None

    related_figure_ids: List[str] = field(default_factory=list)
    related_table_ids: List[str] = field(default_factory=list)
    mentioned_entities: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)
    breadcrumbs: Optional[ChunkBreadcrumbs] = None


@dataclass
class RAGGraphExport:
    """
    Data structure for GraphRAG export containing nodes and edges.
    """
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the export structure to a dictionary.
        """
        return {
            "nodes": self.nodes,
            "edges": self.edges,
        }
