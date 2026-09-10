"""vision_fallback: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.vision_fallback.signals import _TYPE_MAP, log
import base64
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    ContainerUnit,
    FormulaBlock,
    KnowledgeDocument,
    ParagraphBlock,
)

def _get_text(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts)

def _page_crop_b64(doc: KnowledgeDocument, block: Any) -> Optional[str]:
    """Get base64-encoded crop of the block's region from the source PDF.

    Returns None if the source is not available or pymupdf is not installed.
    This is best-effort — the analyzer works without crops by using text prompts.
    """
    vl = getattr(block, "visual_layout", None)
    if not vl:
        return None
    bb = getattr(vl, "bounding_box", None)
    page_idx = getattr(vl, "page_or_screen_index", None)
    if bb is None or page_idx is None:
        return None

    source = doc.source_uri or ""
    if not source or not os.path.isfile(source):
        return None

    try:
        import fitz  # type: ignore[import-untyped]
        pdf = fitz.open(source)
        if page_idx >= len(pdf):
            pdf.close()
            return None
        page = pdf[page_idx]
        pw, ph = page.rect.width, page.rect.height
        margin = 0.02
        clip = fitz.Rect(
            max(0, bb.x0 - margin) * pw,
            max(0, bb.y0 - margin) * ph,
            min(1, bb.x1 + margin) * pw,
            min(1, bb.y1 + margin) * ph,
        )
        pix = page.get_pixmap(clip=clip, dpi=150)
        img_bytes = pix.tobytes("png")
        pdf.close()
        return base64.b64encode(img_bytes).decode()
    except Exception as e:
        log.debug("Could not crop page region: %s", e)
        return None

def _parse_classify_response(text: Optional[str]) -> Tuple[Optional[str], float]:
    if not text:
        return None, 0.0
    lines = text.strip().split("\n")
    block_type = lines[0].strip().lower().rstrip(".")
    mapped = _TYPE_MAP.get(block_type)
    confidence = 0.7
    if len(lines) > 1:
        try:
            confidence = float(lines[1].strip())
            confidence = max(0.3, min(0.95, confidence))
        except ValueError:
            pass
    return mapped, confidence
