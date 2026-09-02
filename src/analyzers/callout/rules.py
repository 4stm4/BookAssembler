"""callout: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.callout.signals import _ICON_MAP, _LABEL_MAP
import re
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    CalloutBlock,
    ContainerUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
)

def _classify(text: str) -> Optional[Tuple[str, str, str, str]]:
    """Return (kind, severity, label, remainder) or None."""
    stripped = text.lstrip()

    for icon, kind, severity in _ICON_MAP:
        if stripped.startswith(icon):
            rest = stripped[len(icon):].lstrip(" .!:—-")
            label, remainder = _split_word_label(rest)
            return kind, severity, (icon + (" " + label if label else "")).strip(), remainder

    for pattern, kind, severity in _LABEL_MAP:
        m = re.match(rf"^\s*(?P<label>{pattern})\s*[!:.—–\-]\s*(?P<rest>.*)$",
                     text, re.IGNORECASE)
        if m:
            return kind, severity, m.group("label"), m.group("rest")

    return None

def _split_word_label(text: str) -> Tuple[str, str]:
    """If text starts with a callout keyword, return (label, rest); else ('', text)."""
    for pattern, _, _ in _LABEL_MAP:
        m = re.match(rf"^(?P<label>{pattern})\s*[!:.—–\-]\s*(?P<rest>.*)$",
                     text, re.IGNORECASE)
        if m:
            return m.group("label"), m.group("rest")
    return "", text

def _replace_first_text(block: ParagraphBlock, new_text: str) -> None:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            if getattr(span, "text", ""):
                span.text = new_text
                return
    block.inlines = [TextLineInline(spans=[StyledTextSpan(text=new_text)])]
