"""page_agent: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.page_agent.signals import FAILURE_BUDGET_RATIO, MIN_BLOCKS, MIN_FAILURE_BUDGET, MIN_NUMERIC_RATIO, MIN_SHORT_RATIO, log
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

from src.analyzers.page_agent.config import JPEG_MAX_DIM, JPEG_QUALITY

@dataclass
class _PageResult:
    """What the agent said about one page. Carries no KRM references."""
    role: str = "text"
    types: Dict[int, str] = field(default_factory=dict)
    table_latex: Optional[str] = None
    failed: bool = False

def _pixmap_to_jpeg(
    pixmap: Any, quality: int = JPEG_QUALITY, max_dim: int = JPEG_MAX_DIM,
) -> bytes:
    import io
    from PIL import Image
    img = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()

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

def _resolve_source_path(doc: KnowledgeDocument) -> Optional[str]:
    """Best-effort: resolve doc.source_uri to a local PDF file the agent can read.

    Handles sep://<provider>/<rel> (unknown provider id): tries every known
    SEP root; also file:// and absolute paths.
    """
    uri = doc.source_uri or ""
    if uri.startswith("file://"):
        p = uri[len("file://") :]
        return p if os.path.exists(p) else None
    if uri.startswith("upload://"):
        filename = uri.replace("upload://", "")
        ssd = os.environ.get("KAE_SSD_PATH", "/data/kae")
        for d in os.listdir(ssd) if os.path.isdir(ssd) else []:
            cand = os.path.join(ssd, d, filename)
            if os.path.isfile(cand):
                return cand
        return None
    if uri.startswith("sep://"):
        try:
            _, rel = uri.replace("sep://", "").split("/", 1)
        except ValueError:
            return None
        # Try both the env-configured SSD path and legacy /data/kae — SEP root
        # can move between deploys, but the file layout under it is stable.
        roots = [
            os.environ.get("KAE_SSD_PATH", "/data/kae"),
            "/data/kae", "/data/ssd",
        ]
        for root in roots:
            cand = os.path.join(root, rel)
            if os.path.exists(cand):
                return cand
        return None
    return uri if os.path.isabs(uri) and os.path.exists(uri) else None
