"""
LaTeX builder + XeLaTeX compiler for the target-document assembly layer.

Implements RFC 0021 (hybrid render) and RFC 0012 (XeLaTeX in locked Docker).
Reads the KRM tree — including visual_layout (bbox) and StyleDescriptor — and
emits a .tex document, then compiles it to PDF with XeLaTeX (Cyrillic-capable
via fontspec + polyglossia). Tombstoned nodes are skipped (RFC 0001 §2.4).
"""

import logging
import os
import subprocess
from typing import Any, List

from src.krm.models import (
    BlankPageBlock,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    FigureBlock,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    ParagraphBlock,
    TableBlock,
    TitlePageBlock,
)

log = logging.getLogger(__name__)

# XeLaTeX preamble: fontspec chooses a Unicode font, polyglossia enables Cyrillic.
_PREAMBLE = r"""\documentclass[11pt]{book}
\usepackage{fontspec}
\usepackage{polyglossia}
\setdefaultlanguage{russian}
\setotherlanguage{english}
\usepackage{graphicx}
\usepackage[a4paper,margin=2.2cm]{geometry}
\usepackage{sectsty}
\setmainfont{DejaVu Serif}
\newfontfamily\cyrillicfont{DejaVu Serif}
\setmonofont{DejaVu Sans Mono}
\sloppy
\begin{document}
"""

_POSTAMBLE = "\n\\end{document}\n"

_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _esc(text: str) -> str:
    """Escape LaTeX special characters."""
    out = []
    for ch in text or "":
        out.append(_SPECIAL.get(ch, ch))
    return "".join(out)


def _para_text(block: ParagraphBlock) -> str:
    parts: List[str] = []
    for inline in (block.inlines or []):
        for span in getattr(inline, "spans", []):
            if hasattr(span, "text"):
                parts.append(span.text)
    return " ".join(parts).strip()


def _alignment(block: Any) -> str:
    """Derive horizontal alignment from the normalized bbox (RFC 0021 §3)."""
    vl = getattr(block, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    if not bb:
        return "left"
    mid = (bb.x0 + bb.x1) / 2.0
    if abs(mid - 0.5) < 0.08 and bb.x0 > 0.15:
        return "center"
    if bb.x1 > 0.82 and bb.x0 > 0.5:
        return "right"
    return "left"


def _wrap_align(latex_body: str, align: str) -> str:
    if align == "center":
        return f"\\begin{{center}}\n{latex_body}\n\\end{{center}}\n"
    if align == "right":
        return f"\\begin{{flushright}}\n{latex_body}\n\\end{{flushright}}\n"
    return latex_body + "\n"


def _heading_cmd(level: int) -> str:
    return {1: "chapter", 2: "section", 3: "subsection"}.get(level, "subsubsection")


def _translated(node: Any, fallback: str, target_lang: str) -> str:
    """Return the translated segment for target_lang if present, else the source.

    RFC 0021: the source is never mutated; translations live under
    metadata['translations'][lang]. Rendering picks the translation when available.
    """
    if not target_lang:
        return fallback
    md = getattr(node, "metadata", None) or {}
    seg = (md.get("translations") or {}).get(target_lang)
    if seg and seg.get("target_text"):
        return seg["target_text"]
    return fallback


def build_latex(doc: KnowledgeDocument, target_lang: str = "") -> str:
    """Render the KRM tree to a XeLaTeX document (hybrid strategy, RFC 0021).

    If target_lang is given, translated segments (metadata['translations']) are
    used in place of source text; the KRM source itself stays unmodified.
    """
    body: List[str] = []
    title = _esc(doc.title or "Untitled")
    body.append(f"\\title{{{title}}}\n\\maketitle\n")

    def render(node: Any, depth: int = 0) -> None:
        if getattr(node, "is_tombstoned", False):
            return  # RFC 0001 §2.4
        if isinstance(node, ContainerUnit):
            if node.title:
                cmd = _heading_cmd(node.level)
                body.append(f"\\{cmd}{{{_esc(_translated(node, node.title, target_lang))}}}\n")
            for child in node.children:
                render(child, depth + 1)
        elif isinstance(node, TitlePageBlock):
            # Special page: centered, larger (cover/title/copyright).
            txt = _esc(_para_text(node))
            if txt:
                body.append("\\begin{center}\n\\Large\n" + txt + "\n\\end{center}\n\\clearpage\n")
        elif isinstance(node, BlankPageBlock):
            body.append("\\clearpage\n")
        elif isinstance(node, CodeBlock):
            # Atomic block: verbatim, never reflowed/split (RFC 0007 §5.2).
            code = node.code_text or ""
            body.append("\\begin{verbatim}\n" + code + "\n\\end{verbatim}\n")
        elif isinstance(node, CaptionBlock):
            cap = _esc(_translated(node, node.caption_text or "", target_lang))
            if cap:
                body.append(f"\\textit{{{cap}}}\n\n")
        elif isinstance(node, ListBlock):
            env = "enumerate" if node.list_style in ("ordered", "alpha", "roman") else "itemize"
            opts = ""
            if node.list_style == "alpha":
                opts = "[label=\\alph*)]"
            elif node.list_style == "roman":
                opts = "[label=\\roman*.]"
            body.append(f"\\begin{{{env}}}{opts}\n")
            for it in node.items:
                if getattr(it, "is_tombstoned", False):
                    continue
                body.append("\\item ")
                for child in it.content:
                    render(child, depth + 1)
            body.append(f"\\end{{{env}}}\n")
        elif isinstance(node, TableBlock):
            body.append(_render_table(node))
        elif isinstance(node, FigureBlock):
            body.append("\\begin{center}[figure]\\end{center}\n")
        elif isinstance(node, ParagraphBlock):
            txt = _esc(_translated(node, _para_text(node), target_lang))
            if txt:
                body.append(_wrap_align(txt, _alignment(node)) + "\n")

    for container in doc.root_containers:
        render(container)

    return _PREAMBLE + "".join(body) + _POSTAMBLE


def _render_table(table: TableBlock) -> str:
    """Render a table atomically (RFC 0007 §5.2).

    If a table agent (GOT-OCR/MinerU) recognized it, use that LaTeX verbatim;
    otherwise fall back to the spatial grid from TableDetector.
    """
    md = getattr(table, "metadata", None) or {}
    recognized = md.get("latex")
    if recognized:
        return "\\begin{center}\n" + recognized + "\n\\end{center}\n"
    grid = getattr(table, "grid", None)
    if not grid:
        return ""
    ncols = max((len(row) for row in grid), default=0)
    if ncols == 0:
        return ""
    col_spec = "|" + "l|" * ncols
    lines = ["\\begin{center}", f"\\begin{{tabular}}{{{col_spec}}}", "\\hline"]
    for row in grid:
        cells = []
        for cell in row:
            cell_text = ""
            for content in getattr(cell, "content", []):
                if isinstance(content, ParagraphBlock):
                    cell_text += _para_text(content)
            cells.append(_esc(cell_text))
        cells += [""] * (ncols - len(cells))
        lines.append(" & ".join(cells) + " \\\\ \\hline")
    lines += ["\\end{tabular}", "\\end{center}", ""]
    return "\n".join(lines)


def compile_xelatex(tex_path: str, work_dir: str) -> str:
    """
    Compile a .tex file to PDF via XeLaTeX (RFC 0012 §3.3, runs in the locked
    Docker image with pinned TeX Live). Returns the PDF path. Two passes resolve
    the table of contents / references.
    """
    base = os.path.splitext(os.path.basename(tex_path))[0]
    for _ in range(2):
        proc = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path],
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1800,
        )
    pdf_path = os.path.join(work_dir, f"{base}.pdf")
    if not os.path.exists(pdf_path):
        tail = proc.stdout.decode("utf-8", "replace")[-2000:] if proc.stdout else ""
        raise RuntimeError(f"XeLaTeX did not produce a PDF. Log tail:\n{tail}")
    return pdf_path
