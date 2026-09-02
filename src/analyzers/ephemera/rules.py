"""ephemera: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.ephemera.signals import MIN_REPEAT_PAGES, _PAGENUM_RE
import re
from typing import Any, Dict, List, Optional
from src.krm.models import (
    ContainerUnit,
    EphemeraBlock,
    KnowledgeDocument,
    ParagraphBlock,
)

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()

def _is_edge(bbox: Any) -> bool:
    """At the very top or bottom of the page, where running heads sit."""
    return bbox.y0 < 0.06 or bbox.y1 > 0.94
