"""ephemera: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.ephemera.signals import (
    BODY_CHARS,
    FOLIO_GAP,
    MIN_REPEAT_PAGES,
    MISREAD_CAPITALS,
    RUNNING_LARGER,
    RUNNING_LINES,
    _PAGENUM_RE,
)
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


def body_sizes(lines: List[Dict[str, Any]]) -> Dict[int, float]:
    """Each scanned page's body size: the middle of its long printed lines'
    (PrintedLinesAnalyzer), by page."""
    by_page: Dict[int, List[float]] = {}
    for line in lines:
        if line.get("size") and len(line.get("text") or "") >= BODY_CHARS:
            by_page.setdefault(line.get("page"), []).append(line["size"])
    return {page: sorted(sizes)[len(sizes) // 2] for page, sizes in by_page.items()}


def margin_line(lines: List[Dict[str, Any]], text: str, body: float) -> bool:
    """Whether a block at a scanned page's edge (_is_edge) is its running
    head or foot by its print (lines, its printed lines): led or closed by
    the page's number set well apart (FOLIO_GAP), or set apart from the
    text by its case or slant alone (RUNNING_LARGER, RUNNING_LINES)."""
    return bool(lines) and (_folio(lines) or _running(lines, text, body))


def _folio(lines: List[Dict[str, Any]]) -> bool:
    words = sorted((w for l in lines for w in l.get("words") or []), key=lambda w: w[0])
    if len(words) < 2:
        return False
    line = lines[0]
    pw, ph = line.get("page_pt") or (1.0, 1.0)
    reach = FOLIO_GAP * (line["box"][3] - line["box"][1]) * ph / pw
    return ((bool(_PAGENUM_RE.match(str(words[0][2]))) and words[1][0] - words[0][1] >= reach)
            or (bool(_PAGENUM_RE.match(str(words[-1][2]))) and words[-1][0] - words[-2][1] >= reach))


def _running(lines: List[Dict[str, Any]], text: str, body: float) -> bool:
    if len(lines) > RUNNING_LINES or any(l.get("bold") for l in lines):
        return False
    sizes = sorted(l.get("size") or 0.0 for l in lines)
    if not body or sizes[len(sizes) // 2] >= RUNNING_LARGER * body:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    capitals = len(letters) >= 4 and sum(ch.islower() for ch in letters) <= MISREAD_CAPITALS * len(letters)
    return capitals or all(l.get("italic") for l in lines)
