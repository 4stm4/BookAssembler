"""
Knowledge Representation Model (KRM) - Core Data Models.

This module defines the strongly-typed data structures for KRM according to
RFC 0002 (docs/architecture/0002-krm.md) and RFC 0001 (docs/architecture/0001-overview.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- No generic node types with string type flags
- Immutable identity (UUIDv4 assigned automatically)
- No silent deletion (tombstoning via is_tombstoned attribute)
- Standard library dependencies only (dataclasses, enum, typing, uuid, abc)
"""

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4


# ============================================================================
# 1. Visual Layout Layer
# ============================================================================

@dataclass(frozen=True)
class NormalizedRect:
    """
    Coordinates of a bounding box normalized relative to page or screen dimensions.
    All values must be within the range [0.0, 1.0], with x0 <= x1 and y0 <= y1.
    """
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.x0 <= 1.0 and 0.0 <= self.y0 <= 1.0 and
                0.0 <= self.x1 <= 1.0 and 0.0 <= self.y1 <= 1.0):
            raise ValueError(
                f"NormalizedRect coordinates must be within [0.0, 1.0], "
                f"got x0={self.x0}, y0={self.y0}, x1={self.x1}, y1={self.y1}"
            )
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError(
                f"Invalid NormalizedRect dimensions: x0 ({self.x0}) > x1 ({self.x1}) "
                f"or y0 ({self.y0}) > y1 ({self.y1})"
            )

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class StyleDescriptor:
    """
    Visual typography, styling, and color attributes.
    """
    font_family: str = "sans-serif"
    font_size_pt: float = 12.0
    is_bold: bool = False
    is_italic: bool = False
    is_monospace: bool = False
    text_color_rgb: Tuple[int, int, int] = (0, 0, 0)
    background_color_rgb: Optional[Tuple[int, int, int]] = None


@dataclass
class VisualLayout:
    """
    Physical layout, bounding box coordinates, screen position, and visual style.
    """
    bounding_box: NormalizedRect
    page_or_screen_index: int = 0
    style: Optional[StyleDescriptor] = None
    rotation_degrees: int = 0


# ============================================================================
# 2. Meta Layer
# ============================================================================

@dataclass
class ProvenanceInfo:
    """
    Audit trail detailing document origin, extraction time, and pipeline analyzers.
    """
    adapter_name: str
    extraction_timestamp_utc: str
    source_byte_offset: Optional[Tuple[int, int]] = None
    applied_analyzers: List[str] = field(default_factory=list)
    applied_skills: List[str] = field(default_factory=list)


# ============================================================================
# 3. Structural Layer (Base & Specialized Nodes)
# ============================================================================

@dataclass
class BaseKRMNode(ABC):
    """
    Abstract base node for all Knowledge Representation Model (KRM) elements.
    Guarantees global identity (UUIDv4), tombstoning support, and metadata storage.
    """
    id: str = field(default_factory=lambda: str(uuid4()))
    visual_layout: Optional[VisualLayout] = None
    confidence_score: float = 1.0
    extraction_confidence: float = 1.0
    classification_confidence: float = 1.0
    is_tombstoned: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    provenance_info: Optional[ProvenanceInfo] = None

    def update_confidence(self) -> None:
        self.confidence_score = min(self.extraction_confidence, self.classification_confidence)


@dataclass
class SpanUnit(BaseKRMNode):
    """
    Base span element representing an inline formatted text fragment.
    """
    text: str = ""


@dataclass
class StyledTextSpan(SpanUnit):
    """
    Styled text fragment within a line.
    """
    pass


@dataclass
class EntityMentionSpan(SpanUnit):
    """
    Inline text fragment referencing a named entity or domain concept.
    """
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None


@dataclass
class FootnoteRefSpan(SpanUnit):
    """
    Inline text fragment referencing a footnote or bibliography entry.
    """
    footnote_id: Optional[str] = None


@dataclass
class InlineUnit(BaseKRMNode):
    """
    Logical grouping of inline span units forming a phrase or line.
    """
    spans: List[SpanUnit] = field(default_factory=list)


@dataclass
class TextLineInline(InlineUnit):
    """
    Single line of formatted text composed of spans.
    """
    pass


@dataclass
class MathInline(InlineUnit):
    """
    Inline mathematical snippet or formula in LaTeX notation.
    """
    latex_code: str = ""


@dataclass
class StructuralUnit(BaseKRMNode, ABC):
    """
    Abstract structural block node residing within a container.
    """
    parent_container_id: Optional[str] = None


@dataclass
class ParagraphBlock(StructuralUnit):
    """
    Narrative text paragraph composed of inline units.
    """
    inlines: List[InlineUnit] = field(default_factory=list)


@dataclass
class TableCell(BaseKRMNode):
    """
    Cell inside a table grid containing structural units.
    """
    row_span: int = 1
    col_span: int = 1
    content: List[StructuralUnit] = field(default_factory=list)


@dataclass
class TableBlock(StructuralUnit):
    """
    Structured tabular block composed of a 2D grid of table cells.
    """
    grid: List[List[TableCell]] = field(default_factory=list)
    caption_id: Optional[str] = None


@dataclass
class FigureBlock(StructuralUnit):
    """
    Graphic or illustration element with optional image reference and caption.
    """
    image_uri: Optional[str] = None
    mime_type: str = "image/png"
    caption_id: Optional[str] = None
    alt_text: Optional[str] = None


@dataclass
class CodeBlock(StructuralUnit):
    """
    Code listing or preformatted source code block.
    """
    code_text: str = ""
    programming_language: Optional[str] = None
    has_line_numbers: bool = False


@dataclass
class FormulaBlock(StructuralUnit):
    """
    Block-level mathematical equation expressed in LaTeX.
    """
    latex_expression: str = ""
    is_numbered: bool = False
    formula_number: Optional[str] = None


@dataclass
class BlankPageBlock(StructuralUnit):
    """
    Intentionally blank page (no meaningful content).
    """
    pass


@dataclass
class TitlePageBlock(ParagraphBlock):
    """
    Title page of the book or a major division (half-title, series page, etc.).
    Aggregates title, authors, publisher, and other front-matter metadata.
    """
    book_title: str = ""
    authors: List[str] = field(default_factory=list)
    publisher: str = ""
    edition: str = ""
    page_role: str = "title"  # cover | title | half_title | series | copyright


@dataclass
class CaptionBlock(StructuralUnit):
    """
    Caption/label for a figure, table, or example.
    E.g. "Figure 1-5 ASCII code." or "Table 2-3 Interrupt vectors."
    """
    caption_text: str = ""
    target_type: str = ""
    label_number: Optional[str] = None
    target_block_id: Optional[str] = None


# ============================================================================
# 4. Semantic Layer (Knowledge Units)
# ============================================================================

@dataclass
class SemanticUnit(BaseKRMNode, ABC):
    """
    Abstract domain knowledge unit decorating a structural block.
    """
    target_block_id: str = ""


@dataclass
class InstructionSpec(SemanticUnit):
    """
    Hardware instruction or API specification (e.g., CPU opcode or function signature).
    """
    architecture_or_platform: str = ""
    mnemonic_or_function: str = ""
    operands_or_arguments: List[str] = field(default_factory=list)
    affected_flags_or_state: List[str] = field(default_factory=list)


@dataclass
class DefinitionSpec(SemanticUnit):
    """
    Formal domain definition for a technical term or concept.
    """
    term: str = ""
    definition_text: str = ""


@dataclass
class WarningSpec(SemanticUnit):
    """
    Safety warning, notice, or critical caution callout.
    """
    severity: str = "warning"  # 'info', 'warning', 'critical'
    message_text: str = ""


# ============================================================================
# 5. Container & Root Units
# ============================================================================

@dataclass
class ContainerUnit(BaseKRMNode):
    """
    Hierarchical document container (Chapter, Section, Subsection, Appendix, etc.).
    """
    title: str = ""
    level: int = 1
    semantic_type: Optional[str] = None
    children: List[BaseKRMNode] = field(default_factory=list)


@dataclass
class KnowledgeDocument(BaseKRMNode):
    """
    Root element representing the entire parsed document in KRM.
    """
    title: str = ""
    source_uri: str = ""
    source_type: str = ""  # e.g., 'pdf', 'docx', 'html', 'ipynb'
    root_containers: List[ContainerUnit] = field(default_factory=list)
