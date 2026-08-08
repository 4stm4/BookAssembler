"""
AI Knowledge Exporter for Knowledge Assembly Engine (KAE).

Exports chunks manifest and GraphRAG knowledge graph dictionaries
according to RFC 0007 (docs/architecture/0007-ai-layer.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (typing)
"""

from typing import Any, Dict, List

from src.ai_layer.models import AIContextChunk
from src.graph.knowledge_graph import KnowledgeGraph


class AIKnowledgeExporter:
    """
    Exporter formatting chunks and graph structures for RAG vector databases and GraphRAG ingestion.
    """

    @staticmethod
    def export_chunks_manifest(chunks: List[AIContextChunk]) -> Dict[str, Any]:
        """
        Exports list of AIContextChunk objects to chunks_manifest.json JSON-compatible dictionary.
        """
        doc_id = "doc_unknown"
        if chunks and chunks[0].metadata.get("document_id"):
            doc_id = str(chunks[0].metadata["document_id"])

        chunks_list: List[Dict[str, Any]] = []
        for chunk in chunks:
            bc_data = {
                "document_title": chunk.breadcrumbs.document_title if chunk.breadcrumbs else "",
                "container_path": chunk.breadcrumbs.container_path if chunk.breadcrumbs else [],
                "page_numbers": chunk.breadcrumbs.page_numbers if chunk.breadcrumbs else [],
            }

            relationships_data = {
                "previous_chunk_id": chunk.previous_chunk_id,
                "next_chunk_id": chunk.next_chunk_id,
                "related_tables": chunk.related_table_ids,
                "related_figures": chunk.related_figure_ids,
                "mentioned_entities": chunk.mentioned_entities,
            }

            chunks_list.append({
                "chunk_id": chunk.chunk_id,
                "chunk_type": chunk.chunk_type,
                "contextual_text": chunk.contextual_text,
                "raw_text": chunk.text_content,
                "breadcrumbs": bc_data,
                "relationships": relationships_data,
                "source_krm_ids": chunk.source_krm_ids,
                "metadata": chunk.metadata,
            })

        return {
            "schema_version": "1.0.0",
            "document_id": doc_id,
            "total_chunks": len(chunks),
            "chunks": chunks_list,
        }

    @staticmethod
    def export_graph_rag(chunks: List[AIContextChunk], kg: KnowledgeGraph) -> Dict[str, Any]:
        """
        Exports chunks and KnowledgeGraph entities/edges into knowledge_graph_rag.json dictionary.
        """
        nodes_map: Dict[str, Dict[str, Any]] = {}
        edges_list: List[Dict[str, Any]] = []

        # 1. Add chunks as nodes and link to mentioned entities
        for chunk in chunks:
            chunk_node_id = chunk.chunk_id
            if chunk_node_id not in nodes_map:
                nodes_map[chunk_node_id] = {
                    "id": chunk_node_id,
                    "label": f"{chunk.chunk_type.capitalize()} Chunk",
                    "type": "chunk",
                }

            for entity_name_or_id in chunk.mentioned_entities:
                entity_id = entity_name_or_id
                entity_label = entity_name_or_id
                entity_type = "entity"

                kg_ent = kg.get_entity(entity_name_or_id)
                if kg_ent is None:
                    for ent in kg._entities.values():
                        if ent.name == entity_name_or_id or ent.canonical_name == entity_name_or_id:
                            kg_ent = ent
                            break

                if kg_ent is not None:
                    entity_id = kg_ent.id
                    entity_label = kg_ent.name
                    entity_type = (
                        kg_ent.entity_type.value
                        if hasattr(kg_ent.entity_type, "value")
                        else str(kg_ent.entity_type)
                    )

                if entity_id not in nodes_map:
                    nodes_map[entity_id] = {
                        "id": entity_id,
                        "label": entity_label,
                        "type": entity_type,
                    }

                edges_list.append({
                    "source": chunk_node_id,
                    "target": entity_id,
                    "relation": "MENTIONS_ENTITY",
                    "weight": 1.0,
                })

        # 2. Add KG entities and edges
        for ent in kg._entities.values():
            if ent.id not in nodes_map:
                nodes_map[ent.id] = {
                    "id": ent.id,
                    "label": ent.name,
                    "type": (
                        ent.entity_type.value
                        if hasattr(ent.entity_type, "value")
                        else str(ent.entity_type)
                    ),
                }

        for edge in kg._edges:
            edges_list.append({
                "source": edge.source_id,
                "target": edge.target_id,
                "relation": (
                    edge.relation_type.value
                    if hasattr(edge.relation_type, "value")
                    else str(edge.relation_type)
                ),
                "weight": edge.confidence,
            })

        return {
            "nodes": list(nodes_map.values()),
            "edges": edges_list,
        }
