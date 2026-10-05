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

import functools
import logging
import math
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.assembler.latex_builder import (
    _esc,
    _is_latin_only,
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

_MM_PER_PT = 25.4 / 72.27
_BP_PER_MM = 72.0 / 25.4
# How far each unit of fontspec's FakeBold moves each edge of a glyph's
# ink out, over the size - measured on XeTeX's output.
_FAKEBOLD_EDGE_EM = 0.005
_FAKEBOLD_MAX = 12.0
_FAKEBOLD_MIN = 0.5
_INK_LEVEL = 160      # 0-255 grey below which a pixel is ink, as the analyzer reads a print

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
        slot.blocks.sort(key=_sort_key)

    headings = sum(
        1 for s in pages.values() for b in s.blocks
        if isinstance(b, ContainerUnit) and b.title
    )
    log.info("page assembly: %d pages, %d blocks, %d container headings",
             len(pages), sum(len(s.blocks) for s in pages.values()), headings)
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
    page_w, page_h = 210.0, 297.0  # A4 mm
    atomic: List[Any] = []
    flow: List[Any] = []
    placed: List[Any] = []

    printed: List[str] = []
    for block in slot.blocks:
        if isinstance(block, _ATOMIC):
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


_FACE_CMD = {"serif": "\\latinfont ", "sans": "\\latinsans ", "mono": "\\latinmono "}
# The TeX Gyre files those families are set from.
_FACE_FILE = {"serif": "texgyretermes", "sans": "texgyreheros", "mono": "texgyrecursor"}


@functools.lru_cache(maxsize=None)
def _font_file(name: str) -> Optional[str]:
    try:
        path = subprocess.run(["kpsewhich", name], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return path or None


@functools.lru_cache(maxsize=4096)
def _ink_in_face(face: str, bold: bool, italic: bool, text: str) -> Optional[Tuple[float, float, float, float, float]]:
    """Where text set in a face inks, per point of its size: from its
    origin to its first ink, its ink's width, its advance, its ink's area
    (per point squared) and its ink's outline. A box is as wide as its
    advance; its ink sits inside it by its first and last glyphs' side
    bearings - a typewriter face's are wide. None where the face's file
    cannot be found."""
    variant = ("bold" if bold else "") + ("italic" if italic else "") or "regular"
    path = _font_file(f"{_FACE_FILE.get(face, 'texgyretermes')}-{variant}.otf")
    if not path or not text.strip():
        return None
    import numpy as np
    import pymupdf
    size, x0, zoom = 100.0, 20.0, 2.0
    doc = pymupdf.open()
    page = doc.new_page(width=x0 * 2 + size * len(text), height=size * 2)
    page.insert_font(fontname="F", fontfile=path)
    page.insert_text((x0, size * 1.4), text, fontsize=size, fontname="F")
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].mean(axis=2)
    ink = grey < _INK_LEVEL
    cols = np.flatnonzero(ink.any(axis=0))
    advance = pymupdf.Font(fontfile=path).text_length(text, fontsize=size)
    doc.close()
    if not len(cols):
        return None
    padded = np.pad(ink, 1)
    edges = int((padded[1:, :] != padded[:-1, :]).sum() + (padded[:, 1:] != padded[:, :-1]).sum())
    unit = zoom * size
    return ((cols[0] / zoom - x0) / size, (cols[-1] + 1 - cols[0]) / unit, advance / size,
            float(ink.sum()) / unit ** 2, edges / unit)



def _printed_lines(block: Any) -> List[Dict[str, Any]]:
    """The lines of a block as its print was read (TocAnalyzer): an
    entry's metadata["printed_lines"], a contents heading's
    metadata["printed_title"]."""
    md = getattr(block, "metadata", None) or {}
    if isinstance(block, ContainerUnit):
        return [md["printed_title"]] if md.get("printed_title") else []
    return list(md.get("printed_lines") or [])


def _printed_nodes(block: Any, target_lang: str, page_w: float, page_h: float) -> List[str]:
    """Each printed line of a block as tikz nodes: its baseline and left
    ink edge where the print's are, at the skew it was scanned at, set in
    the face, weight, slant, size and colour read off it, as heavy as the
    print (FakeBold); each word boxed to where and how wide it printed -
    its face's advances and spaces are not the print's. An underline is
    drawn where the print's runs. A translated title is set once, where
    the title starts, at its own width."""
    source = block.title if isinstance(block, ContainerUnit) else getattr(block, "entry_text", "")
    translated = _translated(block, source or "", target_lang) if target_lang else source
    title_done = False
    out: List[str] = []
    for line in _printed_lines(block):
        text = line["text"]
        fit = True
        if line["part"] in ("title", "heading") and translated != source:
            if title_done:
                continue
            text, fit, title_done = translated, False, True
        if not text.strip():
            continue
        x0, _, x1, _ = line["box"]
        x_mm, y_mm, w_mm = x0 * page_w, line["baseline"] * page_h, (x1 - x0) * page_w
        font = _FACE_CMD.get(line["face"], "") if _is_latin_only(text) else ""
        pieces = (
            [(w[0] * page_w, (w[1] - w[0]) * page_w, w[2], w[3] if len(w) > 3 else None) for w in line["words"]]
            if fit and line.get("words") else [(x_mm, w_mm if fit else None, text, line.get("area"))]
        )
        inks = [_ink_in_face(line["face"], line["bold"], line["italic"], t) if pw and font else None
                for _, pw, t, _ in pieces]
        size_bp, outline_bp = _weighed(line, pieces, inks)
        size = size_bp * 72.27 / 72.0
        weight = ("\\bfseries " if line["bold"] else "") + ("\\itshape " if line["italic"] else "")
        if outline_bp:
            # the scan's spread of ink, which the face as cut does not have
            weight += "\\addfontfeatures{FakeBold=%.1f}" % (outline_bp / (_FAKEBOLD_EDGE_EM * size_bp))
        colour = "\\color[RGB]{%d,%d,%d}" % tuple(line["rgb"]) if line.get("rgb") else ""
        skew = line.get("skew") or 0.0
        # at the skew it was scanned at: over a long line a point or more
        turn = -math.degrees(math.atan(skew))
        style = f"{colour}{font}\\fontsize{{{size:.2f}}}{{{size * 1.2:.2f}}}\\selectfont {weight}"
        outline_mm = outline_bp / _BP_PER_MM
        # Word by word where the print's words were placed (their own
        # widths and spaces are the print's, not the face's), else the
        # line boxed to its printed width.
        for (px, pw, piece, _), ink in zip(pieces, inks):
            py = y_mm + skew * (px - x_mm)
            if ink is not None and pw > 2 * outline_mm:
                # the box widened so that its ink, not its advance, spans
                # the print's, and set off by its first glyph's bearing
                lead, inked, advance = ink[:3]
                scale = (pw - 2 * outline_mm) / (inked * size_bp / _BP_PER_MM)
                px, pw = px + outline_mm - lead * size_bp / _BP_PER_MM * scale, advance * size_bp / _BP_PER_MM * scale
            body = f"\\resizebox{{{pw:.2f}mm}}{{\\height}}{{{_esc(piece)}}}" if pw else _esc(piece)
            out.append(
                f"  \\node[anchor=base west, inner sep=0pt, rotate={turn:.3f}] at ({px:.2f}mm, -{py:.2f}mm) "
                f"{{{style}{body}}};\n"
            )
        if line.get("underline"):
            uy, thick = line["underline"]
            pen = "color={rgb,255:red,%d;green,%d;blue,%d}, " % tuple(line["rgb"]) if line.get("rgb") else ""
            fall = (line.get("skew") or 0.0) * w_mm
            out.append(
                f"  \\draw[{pen}line width={thick:.2f}pt] ({x_mm:.2f}mm, -{uy * page_h:.2f}mm) -- "
                f"({x_mm + w_mm:.2f}mm, -{uy * page_h + fall:.2f}mm);\n"
            )
    return out


def _weighed(line: Dict[str, Any], pieces: List[Any], inks: List[Any]) -> Tuple[float, float]:
    """The size (pt) a printed line is set at and how far FakeBold is to
    move its ink's edges out (pt): as far as makes its words lay as much
    ink as the print's - a scan prints heavier than any face is cut, by
    its spread of ink, which FakeBold reproduces all round as the spread
    does. A glyph's ink then gains its outline times the edge's move; the
    type is set smaller by the move, so its capitals stand as tall as the
    print's."""
    raw = line["size"]
    cap = line.get("cap") or 0.7
    known = [(pw, area, ink) for (_, pw, _, area), ink in zip(pieces, inks)
             if ink is not None and area and pw]
    if not known or raw <= 0:
        return raw, 0.0
    outline = 0.0
    for _ in range(3):
        size = raw - 2.0 * outline / cap
        laid = edge = 0.0
        for w_mm, _, ink in known:
            _, inked, _, area_em, outline_em = ink
            k = max(0.1, (w_mm * _BP_PER_MM - 2.0 * outline) / (inked * size))
            laid += area_em * size * size * k
            edge += outline_em * size * (1.0 + k) / 2.0
        wanted = sum(area for _, area, _ in known)
        outline = max(0.0, (wanted - laid) / edge) if edge else 0.0
        outline = min(outline, _FAKEBOLD_MAX * _FAKEBOLD_EDGE_EM * size)
    size = raw - 2.0 * outline / cap
    if outline < _FAKEBOLD_MIN * _FAKEBOLD_EDGE_EM * size:
        return raw, 0.0
    return size, outline


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
