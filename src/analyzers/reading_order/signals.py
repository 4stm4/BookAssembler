"""reading_order: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

from src.krm.models import BaseKRMNode, CalloutBlock, CaptionBlock, CodeBlock, ContainerUnit, FigureBlock, FootnoteRefSpan, FormulaBlock, InlineUnit, KnowledgeDocument, ListBlock, ParagraphBlock, StructuralUnit, TableBlock

# Blocks that occupy a position in the main reading flow. Lists, captions and
# callouts belong here: a document that declares them (DOCX, HTML) otherwise
# leaves that content outside the Reading Graph, and chunking follows the graph
# (RFC 0007 §2), so it would never reach a chunk. Each is one unit — nested
# content is carried by its parent, not sequenced separately.
_LEAF_TYPES = (
    ParagraphBlock,
    CodeBlock,
    FigureBlock,
    FormulaBlock,
    TableBlock,
    ListBlock,
    CaptionBlock,
    CalloutBlock,
)
