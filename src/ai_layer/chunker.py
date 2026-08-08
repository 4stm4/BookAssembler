"""
Semantic Chunker implementation for Knowledge Assembly Engine (KAE).

Transforms KRM documents, Reading Graph trajectories, and Knowledge Graph relations
into atomic AIContextChunk units according to RFC 0007 (docs/architecture/0007-ai-layer.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- No code/table rupture: atomic blocks (TableBlock, CodeBlock, FormulaBlock, FigureBlock,
  InstructionSpec, DefinitionSpec, WarningSpec) are never split across token limits.
- Contextual breadcrumbs preservation in contextual_text.
- Bidirectional previous_chunk_id / next_chunk_id links.
- Standard library dependencies only (dataclasses, typing, uuid, re).
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from src.ai_layer.models import AIContextChunk, ChunkBreadcrumbs
from src.graph.knowledge_graph import KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph, ReadingTrack
from src.krm.models import (
    BaseKRMNode,
    CodeBlock,
    ContainerUnit,
    DefinitionSpec,
    FigureBlock,
    FormulaBlock,
    InstructionSpec,
    KnowledgeDocument,
    MathInline,
    ParagraphBlock,
    TableBlock,
    TextLineInline,
    WarningSpec,
)


def _estimate_tokens(text: str) -> int:
    """
    Rough estimation of token count (~1 token = 4 characters).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def _extract_text_from_node(node: BaseKRMNode) -> str:
    """
    Extracts plain text content from various KRM structural and semantic node types.
    """
    if isinstance(node, ParagraphBlock):
        lines: List[str] = []
        for inline in node.inlines:
            if isinstance(inline, TextLineInline):
                line_str = "".join(span.text for span in inline.spans)
                if line_str:
                    lines.append(line_str)
            elif isinstance(inline, MathInline):
                if inline.latex_code:
                    lines.append(f"${inline.latex_code}$")
        return "\n".join(lines)

    elif isinstance(node, CodeBlock):
        return node.code_text

    elif isinstance(node, TableBlock):
        row_strings: List[str] = []
        for row in node.grid:
            cell_strings: List[str] = []
            for cell in row:
                cell_texts: List[str] = []
                for unit in cell.content:
                    cell_texts.append(_extract_text_from_node(unit))
                cell_strings.append(" ".join(cell_texts).strip())
            row_strings.append(" | ".join(cell_strings))
        return "\n".join(row_strings)

    elif isinstance(node, FormulaBlock):
        if node.is_numbered and node.formula_number:
            return f"[{node.formula_number}] {node.latex_expression}"
        return node.latex_expression

    elif isinstance(node, FigureBlock):
        caption = node.alt_text or node.caption_id or "Image"
        return f"[Figure: {caption}]"

    elif isinstance(node, InstructionSpec):
        operands = " ".join(node.operands_or_arguments)
        flags = ", ".join(node.affected_flags_or_state)
        return (
            f"Instruction: {node.mnemonic_or_function} {operands}\n"
            f"Architecture: {node.architecture_or_platform}\n"
            f"Flags affected: {flags or 'None'}"
        )

    elif isinstance(node, DefinitionSpec):
        return f"Definition: {node.term} - {node.definition_text}"

    elif isinstance(node, WarningSpec):
        return f"[{node.severity.upper()}]: {node.message_text}"

    return ""


def _get_node_chunk_type_and_lang(node: BaseKRMNode) -> Tuple[str, Optional[str]]:
    """
    Determines chunk type and language/architecture for a KRM node.
    """
    if isinstance(node, CodeBlock):
        return "code", node.programming_language
    elif isinstance(node, TableBlock):
        return "table", None
    elif isinstance(node, FormulaBlock):
        return "formula", None
    elif isinstance(node, FigureBlock):
        return "figure", None
    elif isinstance(node, InstructionSpec):
        return "instruction", node.architecture_or_platform
    elif isinstance(node, DefinitionSpec):
        return "definition", None
    elif isinstance(node, WarningSpec):
        return "warning", None
    elif isinstance(node, ParagraphBlock):
        return "narrative", None
    return "narrative", None


def _is_atomic_block(node: BaseKRMNode) -> bool:
    """
    Returns True if the node is an atomic (non-splittable) block unit.
    """
    return isinstance(
        node,
        (
            TableBlock,
            CodeBlock,
            FormulaBlock,
            FigureBlock,
            InstructionSpec,
            DefinitionSpec,
            WarningSpec,
        ),
    )


class SemanticChunker:
    """
    Chunking engine converting KRM documents and graphs into AIContextChunk objects.
    """

    def __init__(self, max_narrative_tokens: int = 512) -> None:
        self.max_narrative_tokens = max_narrative_tokens

    def _collect_nodes_recursive(
        self,
        container: ContainerUnit,
        current_path: List[str],
    ) -> List[Tuple[BaseKRMNode, str, List[str]]]:
        """
        Recursively collects all structural and semantic nodes from containers along with
        their parent container ID and container path hierarchy.
        """
        collected: List[Tuple[BaseKRMNode, str, List[str]]] = []
        if container.is_tombstoned:
            return collected

        container_path = list(current_path)
        if container.title:
            container_path.append(container.title)

        for child in container.children:
            if child.is_tombstoned:
                continue

            if isinstance(child, ContainerUnit):
                collected.extend(self._collect_nodes_recursive(child, container_path))
            elif isinstance(child, BaseKRMNode):
                collected.append((child, container.id, container_path))

        return collected

    def _get_page_numbers(self, nodes: List[BaseKRMNode]) -> List[int]:
        """
        Extracts sorted 1-based page numbers from the visual layout of nodes.
        """
        pages: Set[int] = set()
        for node in nodes:
            if node.visual_layout is not None:
                pages.add(node.visual_layout.page_or_screen_index + 1)
        if not pages:
            return [1]
        return sorted(list(pages))

    def _extract_graph_links(
        self, krm_ids: List[str], kg: KnowledgeGraph
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Queries Knowledge Graph edges for figure links, table links, and mentioned entities.
        """
        figures: Set[str] = set()
        tables: Set[str] = set()
        entities: Set[str] = set()

        for krm_id in krm_ids:
            for edge in kg.get_outgoing_edges(krm_id):
                entity = kg.get_entity(edge.target_id)
                if entity is not None and entity.name:
                    entities.add(entity.name)
                elif edge.relation_type in (RelationType.CAPTION_FOR, RelationType.REFERENCES):
                    if "fig" in edge.target_id.lower():
                        figures.add(edge.target_id)
                    elif "tbl" in edge.target_id.lower():
                        tables.add(edge.target_id)

            for edge in kg.get_incoming_edges(krm_id):
                entity = kg.get_entity(edge.source_id)
                if entity is not None and entity.name:
                    entities.add(entity.name)

        return sorted(list(figures)), sorted(list(tables)), sorted(list(entities))

    def _create_chunk(
        self,
        doc_title: str,
        doc_id: str,
        nodes: List[BaseKRMNode],
        parent_container_id: str,
        container_path: List[str],
        chunk_type: str,
        language_or_arch: Optional[str],
        kg: KnowledgeGraph,
    ) -> Optional[AIContextChunk]:
        """
        Constructs an AIContextChunk from a set of nodes.
        """
        if not nodes:
            return None

        text_parts: List[str] = []
        source_ids: List[str] = []

        for node in nodes:
            node_text = _extract_text_from_node(node)
            if node_text:
                text_parts.append(node_text)
            source_ids.append(node.id)

        raw_text = "\n\n".join(text_parts).strip()
        if not raw_text:
            return None

        page_numbers = self._get_page_numbers(nodes)
        breadcrumbs = ChunkBreadcrumbs(
            document_title=doc_title,
            container_path=container_path,
            page_numbers=page_numbers,
        )

        contextual_text = f"{breadcrumbs.to_header_string()}\n{raw_text}"

        related_figures, related_tables, mentioned_entities = self._extract_graph_links(
            source_ids, kg
        )

        for node in nodes:
            if isinstance(node, FigureBlock):
                related_figures.append(node.id)
            elif isinstance(node, TableBlock):
                related_tables.append(node.id)

        related_figures = sorted(list(set(related_figures)))
        related_tables = sorted(list(set(related_tables)))

        metadata: Dict[str, Any] = {
            "document_id": doc_id,
            "estimated_tokens": _estimate_tokens(raw_text),
        }

        return AIContextChunk(
            source_krm_ids=source_ids,
            text_content=raw_text,
            contextual_text=contextual_text,
            chunk_type=chunk_type,
            language_or_arch=language_or_arch,
            parent_container_id=parent_container_id,
            related_figure_ids=related_figures,
            related_table_ids=related_tables,
            mentioned_entities=mentioned_entities,
            metadata=metadata,
            breadcrumbs=breadcrumbs,
        )

    def build_chunks(
        self, doc: KnowledgeDocument, rg: ReadingGraph, kg: KnowledgeGraph
    ) -> List[AIContextChunk]:
        """
        Builds semantic chunks from document structure, reading order, and knowledge graph.
        """
        doc_title = doc.title or "Untitled Document"
        doc_id = doc.id

        collected_nodes: List[Tuple[BaseKRMNode, str, List[str]]] = []
        for root_container in doc.root_containers:
            collected_nodes.extend(
                self._collect_nodes_recursive(root_container, current_path=[])
            )

        # Check ReadingGraph sequence
        rg_sequence = rg.get_sequence("root", track=ReadingTrack.MAIN_FLOW)
        node_map = {node_item[0].id: node_item for node_item in collected_nodes}

        ordered_nodes: List[Tuple[BaseKRMNode, str, List[str]]] = []
        visited_ids: Set[str] = set()

        if len(rg_sequence) > 1:
            for n_id in rg_sequence:
                if n_id in node_map and n_id not in visited_ids:
                    ordered_nodes.append(node_map[n_id])
                    visited_ids.add(n_id)

        for item in collected_nodes:
            if item[0].id not in visited_ids:
                ordered_nodes.append(item)
                visited_ids.add(item[0].id)

        chunks: List[AIContextChunk] = []
        narrative_buffer: List[Tuple[BaseKRMNode, str, List[str]]] = []

        def flush_narrative_buffer() -> None:
            if not narrative_buffer:
                return
            b_nodes = [item[0] for item in narrative_buffer]
            b_parent_id = narrative_buffer[0][1]
            b_path = narrative_buffer[0][2]

            chunk = self._create_chunk(
                doc_title=doc_title,
                doc_id=doc_id,
                nodes=b_nodes,
                parent_container_id=b_parent_id,
                container_path=b_path,
                chunk_type="narrative",
                language_or_arch=None,
                kg=kg,
            )
            if chunk is not None:
                chunks.append(chunk)
            narrative_buffer.clear()

        for node, parent_container_id, container_path in ordered_nodes:
            if _is_atomic_block(node):
                flush_narrative_buffer()
                chunk_type, lang = _get_node_chunk_type_and_lang(node)
                chunk = self._create_chunk(
                    doc_title=doc_title,
                    doc_id=doc_id,
                    nodes=[node],
                    parent_container_id=parent_container_id,
                    container_path=container_path,
                    chunk_type=chunk_type,
                    language_or_arch=lang,
                    kg=kg,
                )
                if chunk is not None:
                    chunks.append(chunk)
            else:
                if narrative_buffer:
                    prev_path = narrative_buffer[0][2]
                    curr_tokens = sum(
                        _estimate_tokens(_extract_text_from_node(it[0]))
                        for it in narrative_buffer
                    )
                    new_tokens = _estimate_tokens(_extract_text_from_node(node))

                    if prev_path != container_path or (curr_tokens + new_tokens > self.max_narrative_tokens):
                        flush_narrative_buffer()

                narrative_buffer.append((node, parent_container_id, container_path))

        flush_narrative_buffer()

        # Set bidirectional links
        for i in range(len(chunks)):
            chunks[i].previous_chunk_id = chunks[i - 1].chunk_id if i > 0 else None
            chunks[i].next_chunk_id = chunks[i + 1].chunk_id if i < len(chunks) - 1 else None

        return chunks
