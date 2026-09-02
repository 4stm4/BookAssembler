"""reading_order: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

from src.krm.models import BaseKRMNode, CodeBlock, ContainerUnit, FigureBlock, FootnoteRefSpan, FormulaBlock, InlineUnit, KnowledgeDocument, ParagraphBlock, StructuralUnit, TableBlock

_LEAF_TYPES = (ParagraphBlock, CodeBlock, FigureBlock, FormulaBlock, TableBlock)
