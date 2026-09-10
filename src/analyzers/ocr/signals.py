"""ocr: what marks the entity — vocabularies, patterns, thresholds.

These are the attributes by which the entity is recognised. The methods
that apply them live in rules.py; reading KRM nodes lives in access.py.
"""

import logging
from src.krm.models import ContainerUnit, KnowledgeDocument, NormalizedRect, ParagraphBlock, StyleDescriptor, StyledTextSpan, TextLineInline, VisualLayout

log = logging.getLogger(__name__)

FAILURE_BUDGET_RATIO = 0.5

MIN_FAILURE_BUDGET = 3

# What the model may call a font, mapped onto StyleDescriptor.font_family.
_FONT_FAMILIES = {
    "serif": "serif",
    "sans": "sans-serif",
    "sans-serif": "sans-serif",
    "mono": "monospace",
    "monospace": "monospace",
    "typewriter": "monospace",
}
