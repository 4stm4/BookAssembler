"""ocr: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.ocr.signals import FAILURE_BUDGET_RATIO, MIN_FAILURE_BUDGET, _FONT_FAMILIES, log
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyleDescriptor,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)

def _clamp(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)

def _rect_from(raw: Any, page_box: NormalizedRect) -> Optional[NormalizedRect]:
    """Map a model bbox (0-1000, image-relative) into the page's own box.

    RFC 0002 §inv3 requires [0,1] with x0<=x1, so a box the model reports
    inverted or past the edge is repaired here rather than propagated into
    the KRM (where the NormalizedRect constructor would reject it outright).
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) / 1000.0 for v in raw)
    except (TypeError, ValueError):
        return None
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    w = page_box.x1 - page_box.x0
    h = page_box.y1 - page_box.y0
    return NormalizedRect(
        _clamp(page_box.x0 + x0 * w), _clamp(page_box.y0 + y0 * h),
        _clamp(page_box.x0 + x1 * w), _clamp(page_box.y0 + y1 * h),
    )

def _style_from(obj: Dict[str, Any]) -> Optional[StyleDescriptor]:
    family = _FONT_FAMILIES.get(str(obj.get("font") or "").strip().lower())
    bold = bool(obj.get("bold"))
    if family is None and not bold:
        return None                       # nothing observed worth recording
    return StyleDescriptor(
        font_family=family or "sans-serif",
        is_bold=bold,
        is_monospace=(family == "monospace"),
    )

def _parse_ocr(text: str, page_box: NormalizedRect) -> List[Tuple[
    str, Optional[NormalizedRect], Optional[StyleDescriptor]
]]:
    """Read the model's per-line JSON, tolerating a plain-text answer.

    Asking for geometry does not guarantee getting it. When the model replies
    with bare lines the page still transcribes — those lines just fall back to
    sharing the page box, which is what every line did before geometry was
    requested at all.
    """
    out: List[Tuple[str, Optional[NormalizedRect], Optional[StyleDescriptor]]] = []
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.lower().startswith("json"):
            body = body[4:]

    rows: List[Any] = []
    if body.lstrip().startswith("["):
        try:
            parsed = json.loads(body)
            rows = parsed if isinstance(parsed, list) else []
        except ValueError:
            rows = []
    if not rows:
        for raw in body.splitlines():
            raw = raw.strip().rstrip(",")
            if not raw:
                continue
            if raw.startswith("{"):
                try:
                    rows.append(json.loads(raw))
                    continue
                except ValueError:
                    pass
            rows.append(raw)

    for row in rows:
        if isinstance(row, dict):
            line = str(row.get("text") or "").strip()
            if line:
                out.append((line, _rect_from(row.get("bbox"), page_box),
                            _style_from(row)))
        elif isinstance(row, str) and row.strip():
            out.append((row.strip(), None, None))
    return out

def _needs_ocr(node: Any) -> bool:
    return bool((getattr(node, "metadata", None) or {}).get("needs_ocr"))

def _resolve_source_path(doc: KnowledgeDocument) -> Optional[str]:
    from src.analyzers.page_agent import _resolve_source_path as resolve
    return resolve(doc)
