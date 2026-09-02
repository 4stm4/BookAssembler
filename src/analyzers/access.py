"""Reading KRM nodes — the accessors every analyzer needs.

These answer "what text does this block hold", never "is this block a
footnote": they are not attributes of any entity, so they do not belong in an
entity package. They previously lived as private copies in eight of them and
had silently diverged — `_block_text` had four implementations, `_page_of`
three, and `_first_text` two, one of which returned the whole block despite
its name.

That divergence is not cosmetic. Reading only the first span of a block is
exactly what made EphemeraDetector read the fragment "Analysis" instead of a
full heading and tombstone it as a running head. Where two readings are both
legitimate — a formula must not have spaces inserted between its spans, a
missing font size means "unknown" to one caller and "assume body text" to
another — the difference is a parameter here, not a second implementation
somewhere else.
"""

from typing import Any, Iterator, Optional

def spans(node: Any) -> Iterator[Any]:
    """Every span of every inline, in order."""
    for inline in getattr(node, "inlines", None) or []:
        for span in getattr(inline, "spans", None) or []:
            yield span

def block_text(node: Any, sep: str = " ") -> str:
    """The block's full text, across every inline.

    `sep=""` for content where an inserted space would corrupt the meaning,
    such as a formula split across spans.
    """
    parts = [str(t) for s in spans(node) if (t := getattr(s, "text", ""))]
    return sep.join(parts).strip()

def first_span_text(node: Any) -> str:
    """Text of the first non-empty span — a fragment, not the block.

    Correct only when the decision genuinely concerns the opening of a block
    (a marker, a keyword). Judging a block's length or identity by it is the
    mistake described in this module's docstring.
    """
    for s in spans(node):
        txt = getattr(s, "text", "")
        if txt:
            return str(txt)
    return ""

def page_of(node: Any) -> Optional[int]:
    """Zero-based page index, or None when the node carries no layout."""
    vl = getattr(node, "visual_layout", None)
    return getattr(vl, "page_or_screen_index", None) if vl else None

def style_of(node: Any) -> Optional[Any]:
    vl = getattr(node, "visual_layout", None)
    return getattr(vl, "style", None) if vl else None

def font_size(node: Any, default: Optional[float] = None) -> Optional[float]:
    """Point size, or `default` when the node has no style.

    A size of 0 is treated as absent: it means the adapter found no size, not
    that the text is infinitely small.
    """
    st = style_of(node)
    if st is None:
        return default
    return float(getattr(st, "font_size_pt", 0) or 0) or default
