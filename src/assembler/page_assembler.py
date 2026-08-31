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
    _para_text,
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
REFLOW_ROLES = {"text", "code", "formula", "table", "figure"}


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

    def place(pg: int, node: Any) -> None:
        slot = pages.setdefault(pg, PageSlot(page_index=pg))
        slot.blocks.append(node)
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
            if not any(container is b for slot in pages.values() for b in slot.blocks):
                place(pg, container)
        place(pg, node)

    for c in doc.root_containers:
        walk(c, [])

    for slot in pages.values():
        slot.blocks.sort(key=_sort_key)

    return pages


def _sort_key(block: Any) -> Tuple[float, float]:
    """Reading order within a page: top-to-bottom, then left-to-right.

    Container headings carry no bbox of their own and must stay above the
    content they introduce, so they sort to the top of their page.
    """
    if isinstance(block, ContainerUnit):
        return (-1.0, -1.0)
    vl = getattr(block, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    if bb:
        return (bb.y0, bb.x0)
    return (999.0, 999.0)


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


def assemble_pages(doc: KnowledgeDocument, target_lang: str = "") -> str:
    """Assemble a full LaTeX document page-by-page (RFC 0021 §3 hybrid render)."""
    pages = group_by_page(doc)
    parts: List[str] = []

    for pg_idx in sorted(pages.keys()):
        slot = pages[pg_idx]
        if slot.role == "blank":
            parts.append("\\clearpage\n")
        elif slot.role in POSITIONAL_ROLES:
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
    for block in slot.blocks:
        render_node(body, block, target_lang, recurse=False)
    return "".join(body)


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
    lines: List[str] = []
    lines.append("\\clearpage\n")
    lines.append("\\begin{tikzpicture}[remember picture, overlay, "
                 "shift={(current page.north west)}]\n")

    page_w, page_h = 210.0, 297.0  # A4 mm
    atomic: List[Any] = []

    for block in slot.blocks:
        if isinstance(block, _ATOMIC):
            atomic.append(block)
            continue
        vl = getattr(block, "visual_layout", None)
        bb = getattr(vl, "bounding_box", None) if vl else None
        style = getattr(vl, "style", None) if vl else None
        if not bb:
            continue

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

    lines.append("\\end{tikzpicture}\n")
    for block in atomic:
        render_node(lines, block, target_lang, recurse=False)
    lines.append("\\clearpage\n")
    return "".join(lines)


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
    if isinstance(block, ParagraphBlock):
        return _translated(block, _para_text(block), target_lang)
    if isinstance(block, CaptionBlock):
        return _translated(block, block.caption_text or "", target_lang)
    if isinstance(block, TocEntryBlock):
        num = block.chapter_number or ""
        text = _translated(block, block.entry_text, target_lang)
        page = str(block.target_page + 1) if isinstance(block.target_page, int) else ""
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
