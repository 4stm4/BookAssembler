"""
Deterministic node identity (RFC 0001 §2.3, RFC 0009 §5.2).

A node's id must be stable across runs: re-extracting the same source has to
produce the same KRM, and content-addressed replay (RFC 0012 §4, RFC 0013)
only works if identity is reproducible. Random uuid4 makes both impossible, so
ids for nodes derived from source content are computed with uuid5 over the
facts that define the node.

uuid4 stays correct for genuinely *new* content that is not a function of the
source — HITL edits and translated segments — since two such nodes are distinct
even when their text matches.
"""

import hashlib
from typing import Any, Optional
from uuid import NAMESPACE_URL, UUID, uuid5

# Stable namespace for all derived KRM identities. Never change this: it would
# renumber every node in every previously persisted document.
KAE_NAMESPACE = uuid5(NAMESPACE_URL, "https://kae.local/krm/v1")

_SEP = "\x1f"


def _fmt_bbox(bbox: Any) -> str:
    """Positional key for a node, rounded so float noise cannot split ids."""
    if bbox is None:
        return "-"
    return ":".join(
        f"{getattr(bbox, axis):.6f}" for axis in ("x0", "y0", "x1", "y1")
    )


def derive_id(kind: str, *parts: Any) -> str:
    """Return a stable UUIDv5 string for a node described by `parts`.

    `kind` separates node types that would otherwise share a key (a paragraph
    and the heading promoted from it live at the same bbox).
    """
    key = _SEP.join([kind] + [("" if p is None else str(p)) for p in parts])
    return str(uuid5(KAE_NAMESPACE, key))


def derive_source_id(
    kind: str,
    source_uri: str,
    page_index: Optional[int],
    bbox: Any,
    text: str = "",
    ordinal: Optional[int] = None,
) -> str:
    """Identity for a node extracted directly from the source document.

    Keyed on where it sits and what it says. `ordinal` disambiguates nodes that
    a source can legitimately place at the same spot with the same text.
    """
    digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
    return derive_id(
        kind, source_uri or "", page_index, _fmt_bbox(bbox), digest, ordinal
    )


def derive_composite_id(kind: str, *child_ids: str) -> str:
    """Identity for a node built by aggregating others (a table from its cells).

    Derived from the constituents' ids, so it is stable exactly when they are.
    Order-independent: the same set of children yields the same id regardless of
    the order the detector happened to visit them in.
    """
    return derive_id(kind, *sorted(str(c) for c in child_ids))


def is_derived(node_id: str) -> bool:
    """True if `node_id` was produced by this module rather than uuid4."""
    try:
        return UUID(node_id).version == 5
    except (ValueError, AttributeError, TypeError):
        return False
