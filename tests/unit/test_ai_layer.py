"""
Unit tests for AI Knowledge Layer, Semantic Chunker, and Exporters (RFC 0007).

Tests verify:
1. CodeBlock, TableBlock, and other atomic blocks form non-ruptured single chunks.
2. Breadcrumbs header is correctly formatted and embedded in contextual_text.
3. Bidirectional previous_chunk_id and next_chunk_id pointers between sequential chunks.
4. AIKnowledgeExporter manifest and GraphRAG export dictionary structure and schema.
"""

from typing import Any, Dict, List
import contextlib
import re

try:
    import pytest
except ImportError:
    @contextlib.contextmanager
    def _pytest_raises_fallback(expected_exception: type[BaseException], match: str | None = None) -> Any:
        try:
            yield
        except expected_exception as e:
            if match and not re.search(match, str(e)):
                raise AssertionError(f"Pattern '{match}' not found in exception message: '{e}'")
        else:
            raise AssertionError(f"Expected exception {expected_exception} was not raised")

    class _PytestShim:
        raises = staticmethod(_pytest_raises_fallback)

    pytest = _PytestShim()  # type: ignore[assignment]


from src.ai_layer.chunker import SemanticChunker
from src.ai_layer.exporter import AIKnowledgeExporter
from src.ai_layer.models import AIContextChunk, ChunkBreadcrumbs
from src.graph.knowledge_graph import (
    EntityType,
    KGEntityNode,
    KnowledgeGraph,
    RelationType,
)
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    CodeBlock,
    ContainerUnit,
    InstructionSpec,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TableCell,
    TableBlock,
    TextLineInline,
    VisualLayout,
)


def test_atomic_blocks_non_rupture() -> None:
    """Verify that CodeBlock and TableBlock are not split and form individual atomic chunks."""
    doc = KnowledgeDocument(title="Hardware Architecture Guide")
    container = ContainerUnit(title="Section 1: Code and Tables")

    # Long code block
    long_code = "\n".join([f"MOV AX, {i}" for i in range(100)])
    code_block = CodeBlock(
        code_text=long_code,
        programming_language="x86_asm",
    )

    # Table block
    cell1 = TableCell(content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Header 1")])])])
    cell2 = TableCell(content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Header 2")])])])
    cell3 = TableCell(content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Val 1")])])])
    cell4 = TableCell(content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Val 2")])])])
    table_block = TableBlock(grid=[[cell1, cell2], [cell3, cell4]])

    container.children.append(code_block)
    container.children.append(table_block)
    doc.root_containers.append(container)

    chunker = SemanticChunker(max_narrative_tokens=50)
    chunks = chunker.build_chunks(doc, ReadingGraph(), KnowledgeGraph())

    assert len(chunks) == 2
    assert chunks[0].chunk_type == "code"
    assert chunks[0].language_or_arch == "x86_asm"
    assert "MOV AX, 99" in chunks[0].text_content

    assert chunks[1].chunk_type == "table"
    assert "Header 1 | Header 2" in chunks[1].text_content
    assert "Val 1 | Val 2" in chunks[1].text_content


def test_breadcrumbs_header_formatting() -> None:
    """Verify breadcrumb formatting and presence in contextual_text."""
    bc = ChunkBreadcrumbs(
        document_title="Intel 8086 Reference",
        container_path=["Chapter 2. Instruction Set", "Section 2.1. Data Movement"],
        page_numbers=[12, 13],
    )

    header_str = bc.to_header_string()
    expected_header = "[Context: Intel 8086 Reference | Chapter 2. Instruction Set > Section 2.1. Data Movement | Pages: [12, 13]]"
    assert header_str == expected_header

    # Test chunk generation with visual layout page
    doc = KnowledgeDocument(title="Intel 8086 Reference")
    container = ContainerUnit(title="Chapter 2. Instruction Set")
    rect = NormalizedRect(0.1, 0.1, 0.9, 0.9)
    para = ParagraphBlock(
        visual_layout=VisualLayout(bounding_box=rect, page_or_screen_index=11),
        inlines=[TextLineInline(spans=[StyledTextSpan(text="The MOV instruction copies bytes.")])],
    )
    container.children.append(para)
    doc.root_containers.append(container)

    chunker = SemanticChunker()
    chunks = chunker.build_chunks(doc, ReadingGraph(), KnowledgeGraph())

    assert len(chunks) == 1
    assert chunks[0].contextual_text.startswith("[Context: Intel 8086 Reference | Chapter 2. Instruction Set | Pages: [12]]")
    assert "The MOV instruction copies bytes." in chunks[0].contextual_text


def test_bidirectional_chunk_links() -> None:
    """Verify previous_chunk_id and next_chunk_id links between sequential chunks."""
    doc = KnowledgeDocument(title="Multi-chunk Document")
    container = ContainerUnit(title="Chapter 1")

    p1 = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Paragraph 1 content.")])])
    p2 = ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="Paragraph 2 content.")])])
    code = CodeBlock(code_text="NOP", programming_language="asm")

    container.children.extend([p1, p2, code])
    doc.root_containers.append(container)

    # Use very small max_narrative_tokens to force paragraph separation
    chunker = SemanticChunker(max_narrative_tokens=3)
    chunks = chunker.build_chunks(doc, ReadingGraph(), KnowledgeGraph())

    assert len(chunks) == 3

    # First chunk
    assert chunks[0].previous_chunk_id is None
    assert chunks[0].next_chunk_id == chunks[1].chunk_id

    # Second chunk
    assert chunks[1].previous_chunk_id == chunks[0].chunk_id
    assert chunks[1].next_chunk_id == chunks[2].chunk_id

    # Third chunk
    assert chunks[2].previous_chunk_id == chunks[1].chunk_id
    assert chunks[2].next_chunk_id is None


def test_exporters_manifest_and_graph_rag() -> None:
    """Verify validity of exported JSON dictionaries for chunks manifest and GraphRAG."""
    doc = KnowledgeDocument(title="Doc for Export")
    container = ContainerUnit(title="Section 1")

    instr = InstructionSpec(
        architecture_or_platform="x86",
        mnemonic_or_function="MOV",
        operands_or_arguments=["AX", "BX"],
    )
    container.children.append(instr)
    doc.root_containers.append(container)

    kg = KnowledgeGraph()
    ent = KGEntityNode(name="AX", entity_type=EntityType.REGISTER)
    kg.add_entity(ent)
    kg.add_edge(
        source_id=instr.id,
        target_id=ent.id,
        relation_type=RelationType.USES_REGISTER,
        confidence=0.9,
    )

    chunker = SemanticChunker()
    chunks = chunker.build_chunks(doc, ReadingGraph(), kg)

    # Test chunks_manifest.json export
    manifest_dict = AIKnowledgeExporter.export_chunks_manifest(chunks)
    assert manifest_dict["schema_version"] == "1.0.0"
    assert manifest_dict["total_chunks"] == 1
    assert len(manifest_dict["chunks"]) == 1

    chunk_data = manifest_dict["chunks"][0]
    assert chunk_data["chunk_type"] == "instruction"
    assert "AX" in chunk_data["relationships"]["mentioned_entities"]

    # Test knowledge_graph_rag.json export
    graph_dict = AIKnowledgeExporter.export_graph_rag(chunks, kg)
    assert "nodes" in graph_dict
    assert "edges" in graph_dict

    node_ids = {node["id"] for node in graph_dict["nodes"]}
    assert chunks[0].chunk_id in node_ids
    assert ent.id in node_ids
