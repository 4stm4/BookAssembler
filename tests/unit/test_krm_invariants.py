"""
Unit tests for Knowledge Representation Model (KRM) invariants.

Tests verify:
1. UUIDv4 uniqueness across node creations.
2. NormalizedRect coordinate validation and dimension properties.
3. Class hierarchy, type checks, and tombstoning support.
4. Structure construction for document, containers, blocks, and semantic units.
"""

from typing import Any
from uuid import UUID
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


from src.krm.models import (
    BaseKRMNode,
    CodeBlock,
    ContainerUnit,
    DefinitionSpec,
    EntityMentionSpan,
    FigureBlock,
    FootnoteRefSpan,
    FormulaBlock,
    InstructionSpec,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    MathInline,
    NormalizedRect,
    ParagraphBlock,
    ProvenanceInfo,
    SemanticUnit,
    SpanUnit,
    StyleDescriptor,
    StyledTextSpan,
    StructuralUnit,
    TableBlock,
    TableCell,
    TextLineInline,
    VisualLayout,
    WarningSpec,
)


def test_uuid_uniqueness() -> None:
    """Verify that every created KRM node automatically receives a unique valid UUIDv4 string."""
    node_count = 100
    nodes = [ParagraphBlock() for _ in range(node_count)]
    
    unique_ids = {node.id for node in nodes}
    assert len(unique_ids) == node_count, "All node IDs must be unique"

    for node in nodes:
        # Validate that string is a valid UUIDv4
        parsed_uuid = UUID(node.id, version=4)
        assert str(parsed_uuid) == node.id


def test_normalized_rect_valid() -> None:
    """Verify valid NormalizedRect initialization, width, and height calculations."""
    rect = NormalizedRect(x0=0.1, y0=0.2, x1=0.8, y1=0.9)
    assert rect.x0 == 0.1
    assert rect.y0 == 0.2
    assert rect.x1 == 0.8
    assert rect.y1 == 0.9
    assert abs(rect.width - 0.7) < 1e-6
    assert abs(rect.height - 0.7) < 1e-6


def test_normalized_rect_out_of_bounds() -> None:
    """Verify that NormalizedRect raises ValueError when coordinates exceed [0.0, 1.0]."""
    with pytest.raises(ValueError, match=r"within \[0\.0, 1\.0\]"):
        NormalizedRect(x0=-0.1, y0=0.0, x1=0.5, y1=0.5)

    with pytest.raises(ValueError, match=r"within \[0\.0, 1\.0\]"):
        NormalizedRect(x0=0.0, y0=0.0, x1=1.1, y1=0.5)

    with pytest.raises(ValueError, match=r"within \[0\.0, 1\.0\]"):
        NormalizedRect(x0=0.0, y0=0.0, x1=0.5, y1=1.05)


def test_normalized_rect_inverted_coordinates() -> None:
    """Verify that NormalizedRect raises ValueError when x0 > x1 or y0 > y1."""
    with pytest.raises(ValueError, match=r"Invalid NormalizedRect dimensions"):
        NormalizedRect(x0=0.8, y0=0.1, x1=0.2, y1=0.9)

    with pytest.raises(ValueError, match=r"Invalid NormalizedRect dimensions"):
        NormalizedRect(x0=0.1, y0=0.9, x1=0.8, y1=0.2)


def test_visual_layout_and_style() -> None:
    """Verify VisualLayout creation with StyleDescriptor."""
    rect = NormalizedRect(x0=0.0, y0=0.0, x1=1.0, y1=1.0)
    style = StyleDescriptor(
        font_family="Monaco",
        font_size_pt=10.0,
        is_bold=True,
        is_italic=False,
        is_monospace=True,
        text_color_rgb=(255, 255, 255),
        background_color_rgb=(0, 0, 0),
    )
    layout = VisualLayout(
        bounding_box=rect,
        page_or_screen_index=1,
        style=style,
        rotation_degrees=0,
    )

    assert layout.bounding_box == rect
    assert layout.page_or_screen_index == 1
    assert layout.style is not None
    assert layout.style.font_family == "Monaco"
    assert layout.style.is_bold is True


def test_tombstoning_invariant() -> None:
    """Verify that nodes support tombstoning via is_tombstoned attribute without deletion."""
    paragraph = ParagraphBlock()
    assert paragraph.is_tombstoned is False

    paragraph.is_tombstoned = True
    assert paragraph.is_tombstoned is True


def test_node_type_hierarchy_and_pattern_matching() -> None:
    """Verify that pattern matching via isinstance works cleanly without generic type flags."""
    nodes: list[BaseKRMNode] = [
        ParagraphBlock(),
        TableBlock(),
        FigureBlock(),
        CodeBlock(code_text="mov ax, bx", programming_language="x86_asm"),
        FormulaBlock(latex_expression="E = mc^2"),
        InstructionSpec(mnemonic_or_function="MOV"),
        DefinitionSpec(term="KRM", definition_text="Knowledge Representation Model"),
        WarningSpec(message_text="Deprecated feature"),
    ]

    types_found = [type(n).__name__ for n in nodes]
    expected_types = [
        "ParagraphBlock",
        "TableBlock",
        "FigureBlock",
        "CodeBlock",
        "FormulaBlock",
        "InstructionSpec",
        "DefinitionSpec",
        "WarningSpec",
    ]
    assert types_found == expected_types

    # Ensure all structural blocks inherit from StructuralUnit
    assert isinstance(nodes[0], StructuralUnit)
    assert isinstance(nodes[1], StructuralUnit)
    assert isinstance(nodes[2], StructuralUnit)
    assert isinstance(nodes[3], StructuralUnit)
    assert isinstance(nodes[4], StructuralUnit)

    # Ensure all semantic units inherit from SemanticUnit
    assert isinstance(nodes[5], SemanticUnit)
    assert isinstance(nodes[6], SemanticUnit)
    assert isinstance(nodes[7], SemanticUnit)


def test_knowledge_document_assembly() -> None:
    """Verify hierarchical assembly of a full KnowledgeDocument with containers and blocks."""
    doc = KnowledgeDocument(
        title="Intel 8086 Manual",
        source_uri="file:///docs/intel8086.pdf",
        source_type="pdf",
    )

    chapter = ContainerUnit(title="Chapter 1. Architecture", level=1)
    section = ContainerUnit(title="Section 1.1. Registers", level=2)

    code = CodeBlock(
        code_text="MOV AX, [BX]",
        programming_language="x86_asm",
        has_line_numbers=True,
    )
    para = ParagraphBlock(
        inlines=[
            TextLineInline(
                spans=[
                    StyledTextSpan(text="The MOV instruction copies bytes."),
                    EntityMentionSpan(text="AX", entity_id="ent_reg_ax", entity_type="register"),
                ]
            )
        ]
    )

    section.children.extend([para, code])
    chapter.children.append(section)
    doc.root_containers.append(chapter)

    assert doc.title == "Intel 8086 Manual"
    assert len(doc.root_containers) == 1
    assert len(doc.root_containers[0].children) == 1
    assert len(chapter.children[0].children) == 2  # type: ignore[attr-defined]

    # Check child block properties
    first_child = chapter.children[0].children[0]  # type: ignore[attr-defined]
    assert isinstance(first_child, ParagraphBlock)
    assert len(first_child.inlines) == 1
    assert len(first_child.inlines[0].spans) == 2


def test_list_block_and_item_types() -> None:
    """ListBlock/ListItemBlock: identity, tombstoning, nested content."""
    item1 = ListItemBlock(marker="•", content=[ParagraphBlock()])
    item2 = ListItemBlock(marker="•", content=[ParagraphBlock()])
    lst = ListBlock(list_style="bullet", items=[item1, item2])

    assert isinstance(lst, StructuralUnit)
    assert isinstance(item1, StructuralUnit)
    assert lst.list_style == "bullet"
    assert len(lst.items) == 2
    assert item1.marker == "•"
    assert isinstance(item1.content[0], ParagraphBlock)
    # UUID identity + tombstoning inherited from BaseKRMNode
    assert item1.id != item2.id
    assert lst.is_tombstoned is False
    lst.is_tombstoned = True
    assert lst.is_tombstoned is True

    # Ordered list nests a bullet sub-list — items may contain lists.
    inner = ListBlock(list_style="bullet", items=[ListItemBlock(marker="-")])
    outer = ListBlock(
        list_style="ordered",
        items=[ListItemBlock(marker="1.", content=[inner])],
    )
    assert isinstance(outer.items[0].content[0], ListBlock)


def test_provenance_info() -> None:
    """Verify attaching ProvenanceInfo to a node."""
    provenance = ProvenanceInfo(
        adapter_name="PDFAdapter",
        extraction_timestamp_utc="2026-08-07T14:00:00Z",
        source_byte_offset=(1024, 2048),
        applied_analyzers=["LayoutAnalyzer", "OCRAnalyzer"],
        applied_skills=["IntelManualSkill"],
    )
    node = ParagraphBlock(provenance_info=provenance)
    assert node.provenance_info is not None
    assert node.provenance_info.adapter_name == "PDFAdapter"
    assert len(node.provenance_info.applied_analyzers) == 2
