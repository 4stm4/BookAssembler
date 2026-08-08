"""
AI Knowledge Layer package for Knowledge Assembly Engine (KAE).

Provides semantic chunker, context breadcrumbs, chunk models, and exporters
according to RFC 0007 (docs/architecture/0007-ai-layer.md).
"""

from src.ai_layer.chunker import SemanticChunker
from src.ai_layer.exporter import AIKnowledgeExporter
from src.ai_layer.models import (
    AIContextChunk,
    ChunkBreadcrumbs,
    RAGGraphExport,
)

__all__ = [
    "AIContextChunk",
    "AIKnowledgeExporter",
    "ChunkBreadcrumbs",
    "RAGGraphExport",
    "SemanticChunker",
]
