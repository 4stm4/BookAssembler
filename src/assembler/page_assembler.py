"""
Page assembler — reconstruct pages from KRM blocks grouped by page_or_screen_index.

Implements RFC 0021 §3 (hybrid render):
- Reflow pages (text, code, formula): linear LaTeX flow with alignment from bbox.
- Positional pages (title, cover, toc, diagram): coordinate-based placement via
  tikzpicture overlay, preserving spatial relationships from the original scan.

Does NOT mutate KRM (RFC 0001 §2, RFC 0021 §5.1). Reads visual_layout, bbox,
and StyleDescriptor to reconstruct layout.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.krm.models import (
    BlankPageBlock,
    CalloutBlock,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    EphemeraBlock,
    FigureBlock,
    FootnoteBlock,
    FormulaBlock,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    NormalizedRect,
    ParagraphBlock,
    SidebarBlock,
    TableBlock,
    TitlePageBlock,
    TocEntryBlock,
)

log = logging.getLogger(__name__)

POSITIONAL_ROLES = {"title", "cover", "half_title", "series", "copyright", "toc", "diagram"}
REFLOW_ROLES = {"text", "code", "formula", "table", "figure"}


@dataclass
class PageSlot:
    page_index: int
    role: str = "text"
    blocks: List[Any] = field(default_factory=list)


def group_by_page(doc: KnowledgeDocument) -> Dict[int, PageSlot]:
    """Walk the KRM tree and group non-tombstoned leaf blocks by page index."""
    pages: Dict[int, PageSlot] = {}

    def walk(node: Any) -> None:
        if getattr(node, "is_tombstoned", False):
            return
        if isinstance(node, EphemeraBlock):
            return
        if isinstance(node, ContainerUnit):
            for ch in node.children:
                walk(ch)
            return
        vl = getattr(node, "visual_layout", None)
        pg = getattr(vl, "page_or_screen_index", None) if vl else None
        if pg is None:
            return
        if pg not in pages:
            pages[pg] = PageSlot(page_index=pg)
        slot = pages[pg]
        slot.blocks.append(node)
        _update_role(slot, node)

    for c in doc.root_containers:
        walk(c)

    for slot in pages.values():
        slot.blocks.sort(key=lambda b: _sort_key(b))

    return pages


def _sort_key(block: Any) -> Tuple[float, float]:
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
    elif isinstance(node, BlankPageBlock):
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


def _translated(node: Any, fallback: str, target_lang: str) -> str:
    if not target_lang:
        return fallback
    md = getattr(node, "metadata", None) or {}
    seg = (md.get("translations") or {}).get(target_lang)
    if seg and seg.get("target_text"):
        return seg["target_text"]
    return fallback


_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _esc(text: str) -> str:
    return "".join(_SPECIAL.get(ch, ch) for ch in (text or ""))


def _para_text(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts).strip()


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

    for block in slot.blocks:
        vl = getattr(block, "visual_layout", None)
        bb = getattr(vl, "bounding_box", None) if vl else None
        style = getattr(vl, "style", None) if vl else None
        if not bb:
            continue

        x_mm = bb.x0 * page_w
        y_mm = bb.y0 * page_h
        w_mm = bb.width * page_w
        h_mm = bb.height * page_h

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
    if isinstance(block, ParagraphBlock):
        return _translated(block, _para_text(block), target_lang)
    if isinstance(block, TitlePageBlock):
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
    if isinstance(block, CodeBlock):
        return block.code_text or ""
    if isinstance(block, FormulaBlock):
        return block.latex_expression or ""
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


def _render_reflow(slot: PageSlot, target_lang: str) -> str:
    """Render a reflow page — linear LaTeX with alignment from bbox (RFC 0021 §3)."""
    from src.assembler.latex_builder import (
        _alignment,
        _esc as lb_esc,
        _heading_cmd,
        _para_text as lb_para_text,
        _render_table,
        _translated as lb_translated,
        _wrap_align,
    )

    body: List[str] = []

    for block in slot.blocks:
        if getattr(block, "is_tombstoned", False):
            continue

        if isinstance(block, ParagraphBlock) and not isinstance(block, TitlePageBlock):
            txt = lb_esc(lb_translated(block, lb_para_text(block), target_lang))
            if not txt:
                continue
            md = getattr(block, "metadata", None) or {}
            dec = md.get("semantic_decorator")
            if dec in ("theorem", "proof", "example", "remark", "definition"):
                _ENV = {
                    "theorem": {"theorem": "theorem", "lemma": "lemma",
                                "corollary": "corollary", "proposition": "proposition"},
                    "proof": "proof", "example": "exampleenv",
                    "remark": "remark", "definition": "definitionenv",
                }
                if dec == "theorem":
                    stype = md.get("statement_type", "theorem")
                    env = _ENV["theorem"].get(stype, "theorem")
                elif dec == "proof":
                    env = "proof"
                else:
                    env = _ENV.get(dec, dec)
                body.append(f"\\begin{{{env}}}\n{txt}\n\\end{{{env}}}\n")
            else:
                body.append(_wrap_align(txt, _alignment(block)) + "\n")

        elif isinstance(block, TitlePageBlock):
            txt = lb_esc(lb_para_text(block))
            if txt:
                body.append("\\begin{center}\n\\Large\n" + txt + "\n\\end{center}\n\\clearpage\n")

        elif isinstance(block, CodeBlock):
            code = block.code_text or ""
            body.append("\\begin{verbatim}\n" + code + "\n\\end{verbatim}\n")

        elif isinstance(block, FormulaBlock):
            latex = (block.latex_expression or "").strip()
            md = getattr(block, "metadata", None) or {}
            has_real = not md.get("needs_vision_ocr", False)
            if has_real and latex:
                if block.is_numbered:
                    tag = lb_esc(block.formula_number or "")
                    body.append(f"\\begin{{equation}}\\tag{{{tag}}}\n{latex}\n\\end{{equation}}\n")
                else:
                    body.append(f"\\[\n{latex}\n\\]\n")
            elif latex:
                safe = lb_esc(latex)
                body.append(f"\\[\n\\text{{{safe}}}\n\\]\n")

        elif isinstance(block, TableBlock):
            body.append(_render_table(block))

        elif isinstance(block, CaptionBlock):
            cap = lb_esc(lb_translated(block, block.caption_text or "", target_lang))
            if cap:
                body.append(f"\\textit{{{cap}}}\n\n")

        elif isinstance(block, TocEntryBlock):
            num = lb_esc(block.chapter_number or "")
            title = lb_esc(lb_translated(block, block.entry_text, target_lang))
            page = str(block.target_page + 1) if isinstance(block.target_page, int) else ""
            left = f"{num}~{title}" if num else title
            if page:
                body.append(f"\\noindent {left}\\dotfill {page}\\\\\n")
            else:
                body.append(f"\\noindent {left}\\\\\n")

        elif isinstance(block, FootnoteBlock):
            text = lb_esc(lb_translated(block, block.text, target_lang))
            marker = lb_esc(block.marker) if block.marker else ""
            body.append(f"\\par\\noindent{{\\footnotesize {marker} {text}}}\\par\n")

        elif isinstance(block, ListBlock):
            env = "enumerate" if block.list_style in ("ordered", "alpha", "roman") else "itemize"
            body.append(f"\\begin{{{env}}}\n")
            for it in block.items:
                if getattr(it, "is_tombstoned", False):
                    continue
                body.append("\\item ")
                for child in it.content:
                    if isinstance(child, ParagraphBlock):
                        body.append(lb_esc(lb_translated(child, lb_para_text(child), target_lang)))
                body.append("\n")
            body.append(f"\\end{{{env}}}\n")

        elif isinstance(block, CalloutBlock):
            label = lb_esc(lb_translated(block, block.label or block.kind.title(), target_lang))
            body.append("\\begin{mdframed}\n")
            if label:
                body.append(f"\\textbf{{{label}}}\\\\[0.2em]\n")
            body.append("\\end{mdframed}\n")

        elif isinstance(block, FigureBlock):
            body.append("\\begin{center}[figure]\\end{center}\n")

        elif isinstance(block, BlankPageBlock):
            body.append("\\clearpage\n")

    return "".join(body)
