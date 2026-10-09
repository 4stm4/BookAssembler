"""
Page assembler — reconstruct pages from KRM blocks grouped by page_or_screen_index.

Implements RFC 0021 §3 (hybrid render):
- Reflow pages (text, code, formula): linear LaTeX flow with alignment from bbox.
- Positional pages (title, cover, toc, diagram): coordinate-based placement via
  tikzpicture overlay, preserving spatial relationships from the original scan.

Node-level rendering is delegated to `latex_builder.render_node` — the same
dispatcher the linear builder uses — so no node type can be handled in one mode
and silently dropped in the other.

Does NOT mutate KRM (RFC 0001 §2, RFC 0021 §5.1). Reads visual_layout, bbox,
and StyleDescriptor to reconstruct layout.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.assembler.latex_builder import (
    _esc,
    _figure_ink,
    _para_text,
    _printed_extent,
    _printed_lines,
    _printed_nodes,
    _scan_ink,
    _translated,
    render_node,
)
from src.krm.models import (
    BibEntryBlock,
    BlankPageBlock,
    CalloutBlock,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    EphemeraBlock,
    FootnoteBlock,
    FormulaBlock,
    KnowledgeDocument,
    ListBlock,
    NormalizedRect,
    ParagraphBlock,
    TableBlock,
    TitlePageBlock,
    TocEntryBlock,
)

log = logging.getLogger(__name__)

# RFC 0007 §5.2 (No Code/Table Rupture): these never go through a tikz text node —
# escaping would collapse their whitespace and destroy the markup. On a positional
# page they are emitted in normal flow, below the overlay.
_ATOMIC = (CodeBlock, TableBlock, FormulaBlock)

POSITIONAL_ROLES = {"title", "cover", "half_title", "series", "copyright", "toc", "diagram"}
@dataclass
class PageSlot:
    page_index: int
    role: str = "text"
    blocks: List[Any] = field(default_factory=list)


def _page_of(node: Any) -> Optional[int]:
    vl = getattr(node, "visual_layout", None)
    return getattr(vl, "page_or_screen_index", None) if vl else None


def group_by_page(doc: KnowledgeDocument) -> Dict[int, PageSlot]:
    """Walk the KRM tree and group non-tombstoned nodes by page index.

    ContainerUnit headings are placed on the page of their first content block,
    so chapter/section titles survive page-aware assembly. Nodes without a
    visual_layout inherit the page of the node before them rather than being
    dropped.
    """
    pages: Dict[int, PageSlot] = {}
    state = {"last_page": 0}
    placed_ids: set = set()

    def place(pg: int, node: Any) -> None:
        slot = pages.setdefault(pg, PageSlot(page_index=pg))
        slot.blocks.append(node)
        placed_ids.add(id(node))
        _update_role(slot, node)
        state["last_page"] = pg

    def first_page_under(node: Any) -> Optional[int]:
        pg = _page_of(node)
        if pg is not None:
            return pg
        for child in getattr(node, "children", []) or []:
            pg = first_page_under(child)
            if pg is not None:
                return pg
        return None

    def walk(node: Any, pending: List[ContainerUnit]) -> None:
        if getattr(node, "is_tombstoned", False):
            return
        if isinstance(node, EphemeraBlock):
            return  # headers/footers/page numbers are intentionally omitted

        if isinstance(node, ContainerUnit):
            # A bibliography renders as one atomic `thebibliography` environment
            # (RFC 0007 §5.2), so place the container itself and do not descend —
            # its entries are emitted from inside that environment.
            if node.semantic_type == "bibliography" and any(
                isinstance(c, BibEntryBlock) for c in node.children
            ):
                pg = first_page_under(node)
                place(pg if pg is not None else state["last_page"], node)
                return
            for child in node.children:
                walk(child, pending + [node])
            return

        pg = _page_of(node)
        if pg is None:
            pg = state["last_page"]
        for container in pending:
            if id(container) not in placed_ids:
                place(pg, container)
        place(pg, node)

    for c in doc.root_containers:
        walk(c, [])

    for slot in pages.values():
        slot.blocks = _reading_order(slot.blocks, slot.page_index)

    headings = sum(
        1 for s in pages.values() for b in s.blocks
        if isinstance(b, ContainerUnit) and b.title
    )
    log.info("page assembly: %d pages, %d blocks, %d container headings",
             len(pages), sum(len(s.blocks) for s in pages.values()), headings)
    return pages


# A block wider than this share of its page's text spans its columns: a
# title over both, a single column's paragraph.
_SPAN_SHARE = 0.6


def _box(block: Any, page: Optional[int] = None) -> Optional[NormalizedRect]:
    """Where a block stands on page - none for a heading printed on another
    page than the content it is placed with."""
    vl = getattr(block, "visual_layout", None)
    if vl is None or (page is not None and vl.page_or_screen_index != page):
        return None
    return vl.bounding_box


def _reading_order(blocks: List[Any], page: Optional[int] = None) -> List[Any]:
    """A page's blocks in reading order: top to bottom, a column at a time.

    Sorted by height alone, a two-column page read across both columns at
    once - the paragraph fixture D's right column fell between its left
    column's paragraphs. Blocks standing side by side are columns, read
    left to right, each top to bottom; a block across them (wider than
    _SPAN_SHARE of the page's text) closes the band of columns above it.
    A heading stands where it was printed; a container heading with no box
    of its own stays above its page's content, a block with none at the
    end.
    """
    def placed(b: Any) -> bool:
        return _box(b, page if isinstance(b, ContainerUnit) else None) is not None

    boxed = sorted((b for b in blocks if placed(b)), key=lambda b: (_box(b).y0, _box(b).x0))
    head = [b for b in blocks if not placed(b) and isinstance(b, ContainerUnit)]
    tail = [b for b in blocks if not placed(b) and not isinstance(b, ContainerUnit)]
    if not boxed:
        return head + tail
    left = min(_box(b).x0 for b in boxed)
    width = max(_box(b).x1 for b in boxed) - left
    out: List[Any] = []
    band: List[Any] = []
    for block in boxed:
        bb = _box(block)
        if bb.x1 - bb.x0 > _SPAN_SHARE * width:
            out.extend(_by_column(band))
            band = []
            out.append(block)
        else:
            band.append(block)
    out.extend(_by_column(band))
    return head + out + tail


# A page's columns start together, at the top of their band, within this
# share of the page's height.
_COLUMN_TOP = 0.02


def _by_column(band: List[Any]) -> List[Any]:
    """Blocks side by side read a column at a time: those whose spans across
    overlap, chained, are one column. Columns start together at the top of
    their band; blocks side by side that do not are a figure's pieces -
    the paragraph fixture C's label table beside the second of two
    registers, a register over both - read top to bottom."""
    columns: List[List[Any]] = []
    spans: List[List[float]] = []
    for block in sorted(band, key=lambda b: _box(b).x0):
        bb = _box(block)
        if spans and bb.x0 < spans[-1][1]:
            columns[-1].append(block)
            spans[-1][1] = max(spans[-1][1], bb.x1)
        else:
            columns.append([block])
            spans.append([bb.x0, bb.x1])
    tops = [min(_box(b).y0 for b in column) for column in columns]
    if len(columns) > 1 and max(tops) - min(tops) > _COLUMN_TOP:
        return sorted(band, key=lambda b: (_box(b).y0, _box(b).x0))
    return [b for column in columns for b in sorted(column, key=lambda b: (_box(b).y0, _box(b).x0))]


def _update_role(slot: PageSlot, node: Any) -> None:
    if isinstance(node, TitlePageBlock):
        slot.role = getattr(node, "page_role", "title")
    elif isinstance(node, TocEntryBlock) and slot.role == "text":
        slot.role = "toc"
    elif isinstance(node, BlankPageBlock) and slot.role == "text":
        slot.role = "blank"
    md = getattr(node, "metadata", None) or {}
    agent_role = md.get("page_role")
    if agent_role and agent_role in POSITIONAL_ROLES:
        slot.role = agent_role


def layout_for(slot: PageSlot) -> str:
    """Which render strategy a page gets (RFC 0021 §3): positional | reflow | blank.

    The single source of truth for that decision. The editor asks the server for
    it rather than reimplementing the rule in TypeScript — a second copy would
    drift from this one exactly as the LaTeX reflow renderer once drifted from
    the linear builder.
    """
    def renders_something(b: Any) -> bool:
        if isinstance(b, BlankPageBlock):
            return False
        # A container contributes a heading or nothing at all.
        if isinstance(b, ContainerUnit):
            return bool(b.title)
        return True

    if slot.role == "blank" and not any(renders_something(b) for b in slot.blocks):
        return "blank"
    if slot.role in POSITIONAL_ROLES:
        return "positional"
    return "reflow"


def page_layout_map(doc: KnowledgeDocument) -> List[Dict[str, Any]]:
    """Per-page layout decision plus the ids on each page, for the editor."""
    pages = group_by_page(doc)
    sizes = (doc.metadata or {}).get("page_sizes_pt") or []
    out: List[Dict[str, Any]] = []
    for idx in sorted(pages):
        slot = pages[idx]
        entry: Dict[str, Any] = {
            "page_index": idx,
            "role": slot.role,
            "layout": layout_for(slot),
            "block_ids": [b.id for b in slot.blocks],
        }
        # The page's real size: a reconstruction drawn on A4 put a scan's text
        # at the wrong scale (RFC 0021 §3 — positional render keeps size).
        if idx < len(sizes) and sizes[idx]:
            entry["width_pt"], entry["height_pt"] = sizes[idx][0], sizes[idx][1]
        out.append(entry)
    return out


def assemble_pages(doc: KnowledgeDocument, target_lang: str = "") -> str:
    """Assemble a full LaTeX document page-by-page (RFC 0021 §3 hybrid render)."""
    pages = group_by_page(doc)
    parts: List[str] = []

    for pg_idx in sorted(pages.keys()):
        slot = pages[pg_idx]
        layout = layout_for(slot)
        log.debug("page %d role=%s layout=%s blocks=%d (%s)", pg_idx, slot.role,
                  layout, len(slot.blocks),
                  ", ".join(sorted({type(b).__name__ for b in slot.blocks})))
        if layout == "blank":
            parts.append("\\clearpage\n")
        elif layout == "positional":
            parts.append(_render_positional(slot, target_lang))
        else:
            parts.append(_render_reflow(slot, target_lang))

    return "".join(parts)


def _render_reflow(slot: PageSlot, target_lang: str) -> str:
    """Render a reflow page — linear LaTeX with alignment from bbox (RFC 0021 §3).

    Containers render heading-only (`recurse=False`): their children are already
    grouped onto their own pages by `group_by_page`.
    """
    body: List[str] = []
    above: Optional[Tuple[float, float, float, float]] = None
    extents = [_printed_extent(block) for block in slot.blocks]
    lefts = _column_lefts(extents)
    for block, here, left in zip(slot.blocks, extents, lefts):
        if here and above and here[0] < above[2] and above[0] < here[2] and here[1] > above[3]:
            # Two blocks set as printed, one under the other in a column,
            # stand as far apart as the print left them - not TeX's line
            # skip, which set a paragraph against the heading over it.
            body.append("\\par\\nointerlineskip\\vspace{%.2fmm}\n" % (here[1] - above[3]))
        render_node(body, block, target_lang, recurse=False, column_left=left)
        above = here
    return "".join(body)


def _column_lefts(extents: List[Optional[Tuple[float, float, float, float]]]) -> List[Optional[float]]:
    """Where (mm) the column each block set as printed stands in starts -
    extents are their inks' x0, top, x1, bottom, None for a block not set
    as printed: the leftmost ink of the blocks over and under it, those
    whose spans across overlap its own. A block reaching across into a
    column beside them - a heading over both columns - has no say in where
    theirs starts; its own starts where the leftmost it reaches over does.
    Set from the flow's edge, a paragraph of a line alone lost its first
    line's indent, a number set under its example stood under the margin."""
    def across(a: Tuple[float, ...], b: Tuple[float, ...]) -> bool:
        return a[0] < b[2] and b[0] < a[2]

    def beside(a: Tuple[float, ...], b: Tuple[float, ...]) -> bool:
        return not across(a, b) and a[1] < b[3] and b[1] < a[3]

    placed = [e for e in extents if e]
    lefts: List[Optional[float]] = []
    for e in extents:
        if not e:
            lefts.append(None)
            continue
        column = [f for f in placed if across(e, f)]
        aside = [g for f in column for g in placed if beside(f, g)]
        own = [f for f in column if not any(across(f, g) for g in aside)]
        lefts.append(min(f[0] for f in (own if e in own else column)))
    return lefts


def _font_size_cmd(style: Any) -> str:
    if not style:
        return ""
    pt = getattr(style, "font_size_pt", 12.0)
    if pt >= 20:
        return r"\Large "
    if pt >= 16:
        return r"\large "
    if pt <= 8:
        return r"\footnotesize "
    if pt <= 10:
        return r"\small "
    return ""


def _render_positional(slot: PageSlot, target_lang: str) -> str:
    """Render a positional page using tikzpicture overlay (RFC 0021 §3)."""
    page_w, page_h = 210.0, 297.0  # A4 mm
    atomic: List[Any] = []
    flow: List[Any] = []
    placed: List[Any] = []

    printed: List[str] = []
    for block in slot.blocks:
        if _figure_ink(block):
            # a figure of a scanned page, drawn from its own ink where it
            # printed (DiagramDetectorAnalyzer)
            printed.append(_scan_ink(_figure_ink(block), page_w, page_h, (0.0, 0.0), ""))
        elif isinstance(block, _ATOMIC):
            atomic.append(block)
        elif _printed_lines(block):
            # Read off its print line by line (TocAnalyzer): each line is
            # set where, how large and in what type it was printed.
            printed.extend(_printed_nodes(block, target_lang, page_w, page_h))
        elif _positioned_lines(block):
            # A merged block whose inlines kept their own geometry (a title
            # page) is placed line by line — that layout is what makes the page
            # a title page (RFC 0021 §3, §5.4).
            placed.extend(_positioned_lines(block))
        elif getattr(getattr(block, "visual_layout", None), "bounding_box", None):
            placed.append(block)
        else:
            # No bbox to position by — container headings above all. Emitting
            # them in normal flow ahead of the page keeps document structure;
            # dropping them (the earlier behaviour) lost every \chapter on a
            # title or toc page.
            flow.append(block)

    lines: List[str] = []
    for block in flow:
        render_node(lines, block, target_lang, recurse=False)
    lines.append("\\clearpage\n")
    lines.append("\\begin{tikzpicture}[remember picture, overlay, "
                 "shift={(current page.north west)}]\n")

    for block in placed:
        vl = block.visual_layout
        bb = vl.bounding_box
        style = getattr(vl, "style", None)

        x_mm = bb.x0 * page_w
        y_mm = bb.y0 * page_h
        w_mm = bb.width * page_w

        text = _block_text(block, target_lang)
        if not text:
            continue

        escaped = _esc(text)
        size_cmd = _font_size_cmd(style)
        bold = r"\bfseries " if style and getattr(style, "is_bold", False) else ""
        italic = r"\itshape " if style and getattr(style, "is_italic", False) else ""

        align = _tikz_align(bb)
        anchor = "north west" if align == "left" else "north" if align == "center" else "north east"

        x_anchor = x_mm if align == "left" else (x_mm + w_mm / 2) if align == "center" else (x_mm + w_mm)

        lines.append(
            f"  \\node[anchor={anchor}, text width={w_mm:.1f}mm, "
            f"align={align}, inner sep=0pt] "
            f"at ({x_anchor:.1f}mm, -{y_mm:.1f}mm) "
            f"{{{size_cmd}{bold}{italic}{escaped}}};\n"
        )

    lines.extend(printed)
    lines.append("\\end{tikzpicture}\n")
    for block in atomic:
        render_node(lines, block, target_lang, recurse=False)
    lines.append("\\clearpage\n")
    return "".join(lines)


def _positioned_lines(block: Any) -> List[Any]:
    """Inlines of `block` that carry their own bbox, if more than one does.

    A block whose lines were merged from separate source nodes keeps each one's
    geometry on the inline (RFC 0021 §5.4). One such line is just the block, so
    only a genuine multi-line layout is worth placing separately.
    """
    lines = [
        il for il in (getattr(block, "inlines", None) or [])
        if getattr(getattr(il, "visual_layout", None), "bounding_box", None)
    ]
    return lines if len(lines) > 1 else []


def _tikz_align(bb: NormalizedRect) -> str:
    mid = (bb.x0 + bb.x1) / 2.0
    if abs(mid - 0.5) < 0.08 and bb.x0 > 0.15:
        return "center"
    if bb.x1 > 0.82 and bb.x0 > 0.5:
        return "right"
    return "left"


def _block_text(block: Any, target_lang: str) -> str:
    """Flatten a block to plain text for placement inside a tikz node.

    TitlePageBlock is a ParagraphBlock subclass, so the paragraph branch covers
    both.
    """
    spans = getattr(block, "spans", None)
    if spans is not None and not hasattr(block, "inlines"):
        # An inline placed on its own (see _positioned_lines).
        return " ".join(s.text for s in spans if hasattr(s, "text")).strip()
    if isinstance(block, ParagraphBlock):
        return _translated(block, _para_text(block), target_lang)
    if isinstance(block, CaptionBlock):
        return _translated(block, block.caption_text or "", target_lang)
    if isinstance(block, TocEntryBlock):
        num = block.chapter_number or ""
        text = _translated(block, block.entry_text, target_lang)
        page = block.page_label or (
            str(block.target_page + 1) if isinstance(block.target_page, int) else ""
        )
        return f"{num} {text} {'.' * 3} {page}".strip() if page else f"{num} {text}".strip()
    if isinstance(block, FootnoteBlock):
        return _translated(block, block.text, target_lang)
    if isinstance(block, ContainerUnit):
        return _translated(block, block.title or "", target_lang)
    if isinstance(block, CalloutBlock):
        parts = []
        if block.label:
            parts.append(block.label)
        for c in block.content:
            t = _block_text(c, target_lang)
            if t:
                parts.append(t)
        return " ".join(parts)
    if isinstance(block, ListBlock):
        items = []
        for it in block.items:
            for c in it.content:
                t = _block_text(c, target_lang)
                if t:
                    items.append(t)
        return "\n".join(items)
    return ""
