"""
Geometry helpers over NormalizedRect (RFC 0002 §inv3, RFC 0021 §5.4).

Kept next to the model rather than inside one analyzer: several stages merge
nodes and must give the merged node the region it actually covers. A whole-page
rect is the coordinate-zeroing RFC 0021 §5.4 forbids.
"""

from typing import Any, Iterable, List, Optional

from src.krm.models import NormalizedRect


def bbox_of(node: Any) -> Optional[NormalizedRect]:
    vl = getattr(node, "visual_layout", None)
    return getattr(vl, "bounding_box", None) if vl else None


def union_bbox(nodes: Iterable[Any], pad: float = 0.0) -> Optional[NormalizedRect]:
    """Smallest rect covering every node that carries a bbox, clamped to [0,1].

    Returns None when no node has geometry, so callers can tell "nothing to
    place" apart from "covers the page".
    """
    bbs: List[NormalizedRect] = [b for b in (bbox_of(n) for n in nodes) if b]
    if not bbs:
        return None
    return NormalizedRect(
        max(0.0, min(b.x0 for b in bbs) - pad),
        max(0.0, min(b.y0 for b in bbs) - pad),
        min(1.0, max(b.x1 for b in bbs) + pad),
        min(1.0, max(b.y1 for b in bbs) + pad),
    )
