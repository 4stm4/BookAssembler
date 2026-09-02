"""definition: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.definition.signals import _DEFINITION_PATTERN_RE, _DEFINITION_PREFIX_RE
import re
from typing import Any, Dict, List, Optional
from src.krm.models import (
    ContainerUnit,
    DefinitionSpec,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
)

def _has_styled_lead(block: ParagraphBlock) -> Optional[str]:
    """Return the text of the first span if it's italic or bold."""
    for inline in block.inlines or []:
        spans = getattr(inline, "spans", []) or []
        if not spans:
            continue
        first = spans[0]
        if not isinstance(first, StyledTextSpan):
            return None
        style = getattr(first, "style", None)
        if style and (getattr(style, "is_italic", False) or getattr(style, "is_bold", False)):
            return getattr(first, "text", "") or ""
    return None
