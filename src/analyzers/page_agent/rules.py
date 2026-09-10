"""page_agent: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.page_agent.signals import FAILURE_BUDGET_RATIO, MIN_BLOCKS, MIN_FAILURE_BUDGET, MIN_NUMERIC_RATIO, MIN_SHORT_RATIO, log
from src.analyzers.source_io import pixmap_to_jpeg, resolve_source_path
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TextLineInline,
    StyledTextSpan,
    VisualLayout,
)

@dataclass
class _PageResult:
    """What the agent said about one page. Carries no KRM references."""
    role: str = "text"
    types: Dict[int, str] = field(default_factory=dict)
    table_latex: Optional[str] = None
    failed: bool = False

def _clean_tabular(raw: Any) -> Optional[str]:
    """Return a LaTeX tabular from a model reply, or None if there is none.

    Models wrap code in markdown fences often enough that accepting the raw
    string would put ``` into the document.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or "tabular" not in s.lower():
        return None
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    return s or None

def _text(node: Any) -> str:
    if isinstance(node, ParagraphBlock):
        return " ".join(
            s.text for i in (node.inlines or [])
            for s in getattr(i, "spans", []) if hasattr(s, "text")
        ).strip()
    return (getattr(node, "title", "") or "").strip()

def _looks_numeric(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 40:
        return False
    digits = sum(c.isdigit() for c in t)
    return digits >= 1 and digits / max(1, len(t)) >= 0.3
