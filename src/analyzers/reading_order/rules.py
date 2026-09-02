"""reading_order: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.reading_order.signals import _LEAF_TYPES
from src.krm.models import (
    BaseKRMNode,
    CodeBlock,
    ContainerUnit,
    FigureBlock,
    FootnoteRefSpan,
    FormulaBlock,
    InlineUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StructuralUnit,
    TableBlock,
)

