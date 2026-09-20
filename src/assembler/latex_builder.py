"""
LaTeX builder + XeLaTeX compiler for the target-document assembly layer.

Implements RFC 0021 (hybrid render) and RFC 0012 (XeLaTeX in locked Docker).
Reads the KRM tree — including visual_layout (bbox) and StyleDescriptor — and
emits a .tex document, then compiles it to PDF with XeLaTeX (Cyrillic-capable
via fontspec + polyglossia). Tombstoned nodes are skipped (RFC 0001 §2.4).
"""

import logging
import os
import re
import subprocess
from typing import Any, List, Optional

from src.security.manager import Capability, get_security_manager
from src.krm.models import (
    AlgorithmBlock,
    BibEntryBlock,
    BlankPageBlock,
    CalloutBlock,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    EphemeraBlock,
    FigureBlock,
    FootnoteBlock,
    IndexEntryBlock,
    KnowledgeDocument,
    FormulaBlock,
    ListBlock,
    ParagraphBlock,
    SidebarBlock,
    TableBlock,
    TitlePageBlock,
    TocEntryBlock,
)

log = logging.getLogger(__name__)

# XeLaTeX preamble: fontspec chooses a Unicode font, polyglossia enables Cyrillic.
_PREAMBLE = r"""\documentclass[11pt]{book}
\usepackage{fontspec}
\usepackage{polyglossia}
\setdefaultlanguage{russian}
\setotherlanguage{english}
\usepackage{amsmath}
\usepackage{amsthm}
\usepackage{graphicx}
\usepackage{array}
\usepackage{multirow}
\usepackage{colortbl}  % \cellcolor; xcolor itself arrives via tikz below
\newtheorem{theorem}{Theorem}[chapter]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{corollary}[theorem]{Corollary}
\newtheorem{proposition}[theorem]{Proposition}
\newtheorem{remark}{Remark}[chapter]
\newtheorem{exampleenv}{Example}[chapter]
\theoremstyle{definition}
\newtheorem{definitionenv}{Definition}[chapter]
\usepackage{framed}  % lightweight alternative to algorithm2e
\usepackage[framemethod=default]{mdframed}
\usepackage{tikz}
\usepackage[a4paper,margin=2.2cm]{geometry}
\usepackage{sectsty}
\setmainfont{DejaVu Serif}
\newfontfamily\cyrillicfont{DejaVu Serif}
\setmonofont{DejaVu Sans Mono}
% TeX Gyre Termes (fonts-texgyre, installed in the Docker image
% specifically for this) is a metric-compatible OTF clone of Times -
% much closer to a scanned source page's own Times-Roman than either
% DejaVu Serif or Latin Modern Roman (tried first: a real font, but a
% Computer Modern derivative, not Times-shaped at all). It has no
% Cyrillic glyphs either (confirmed: xelatex reports "Missing
% character" for every Cyrillic codepoint under it) - same gap Latin
% Modern had - so it cannot replace DejaVu Serif as the document's main
% font; the source stays multilingual (RFC 0021, polyglossia/russian).
% Cells whose text has no non-Latin characters switch to this family
% instead (see _is_latin_only below), leaving DejaVu Serif as the
% fallback for anything that needs it.
\newfontfamily\latinfont{TeX Gyre Termes}
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


# Primitives a model- or OCR-authored fragment (formula LaTeX, table LaTeX,
# reconstructed TikZ) never legitimately needs, and which would let it read
# host files into the PDF or wedge the compiler. The whole document is built
# from an untrusted upload, so these fragments — the only places raw,
# unescaped LaTeX from a model reaches the output — are filtered before
# xelatex (which already runs without -shell-escape). A stripped primitive
# becomes \relax (a no-op); its braced argument stays as literal text.
_LATEX_FORBIDDEN = re.compile(
    r"\\(?:input|include|includegraphics|write|openin|openout|read|catcode|"
    r"def|edef|xdef|gdef|let|futurelet|csname|expandafter|immediate|special|"
    r"usepackage|RequirePackage|directlua|shipout|newread|newwrite|"
    r"InputIfFileExists|IfFileExists|lstinputlisting|batchmode|scrollmode)"
    r"(?![A-Za-z@])",
)


def _sanitize_latex_fragment(text: str) -> str:
    """Neutralise file/IO/programming primitives in a model-authored LaTeX
    fragment. Math, tabular and TikZ drawing markup pass through untouched."""
    if not text:
        return text
    return _LATEX_FORBIDDEN.sub(r"\\relax ", text)


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
    if seg and seg.get("merged_into"):
        # The page break cut this block's sentence: its text went out, and
        # came back, inside the translation of the block it continues.
        return ""
    if seg and seg.get("target_text"):
        return seg["target_text"]
    return fallback


def build_latex(
    doc: KnowledgeDocument, target_lang: str = "", page_aware: bool = False,
) -> str:
    """Render the KRM tree to a XeLaTeX document (hybrid strategy, RFC 0021).

    If target_lang is given, translated segments (metadata['translations']) are
    used in place of source text; the KRM source itself stays unmodified.

    If page_aware is True, blocks are grouped by page_or_screen_index and
    rendered per-page with positional layout for special pages (title, toc,
    cover) and reflow for text pages (RFC 0021 §3).
    """
    if page_aware:
        # No synthetic \maketitle here: assemble_pages already renders the
        # source's own title/cover page positionally, at its real
        # page_or_screen_index (POSITIONAL_ROLES in page_assembler.py). A
        # \maketitle banner would insert an extra page with no source page
        # index of its own, permanently offsetting every page after it from
        # its counterpart in the original — breaking the page correspondence
        # this pipeline exists to preserve.
        return _PREAMBLE + assemble_pages(doc, target_lang) + _POSTAMBLE

    body: List[str] = []
    title = _esc(doc.title or "Untitled")
    body.append(f"\\title{{{title}}}\n\\maketitle\n")

    for container in doc.root_containers:
        render_node(body, container, target_lang)

    return _PREAMBLE + "".join(body) + _POSTAMBLE


def render_node(
    body: List[str], node: Any, target_lang: str = "",
    depth: int = 0, recurse: bool = True,
) -> None:
    """Render one KRM node into `body` as LaTeX fragments.

    Single dispatcher shared by the linear builder (`build_latex`) and the
    page-aware assembler, so every node type is handled identically in both
    modes and neither can silently drop content.

    `recurse=False` renders a ContainerUnit's heading only, without descending
    into children — the page-aware assembler places those children itself, on
    the pages their bbox says they belong to. Bibliography containers are always
    rendered whole: `thebibliography` is one atomic environment.
    """
    def render(n: Any, d: int = 0) -> None:
        render_node(body, n, target_lang, d, recurse=True)

    if getattr(node, "is_tombstoned", False):
        return  # RFC 0001 §2.4
    if isinstance(node, ContainerUnit):
        if node.semantic_type == "bibliography":
            entries = [c for c in node.children if isinstance(c, BibEntryBlock)]
            if entries:
                if node.title:
                    cmd = _heading_cmd(node.level)
                    body.append(
                        f"\\{cmd}*{{{_esc(_translated(node, node.title, target_lang))}}}\n"
                    )
                widest = str(len(entries))
                body.append(f"\\begin{{thebibliography}}{{{widest}}}\n")
                for entry in entries:
                    if entry.is_tombstoned:
                        continue
                    key = _esc(entry.cite_key or entry.id[:8])
                    raw = _esc(_translated(entry, entry.raw_text or entry.title, target_lang))
                    body.append(f"\\bibitem{{{key}}} {raw}\n")
                body.append("\\end{thebibliography}\n")
                return
        if node.title:
            cmd = _heading_cmd(node.level)
            body.append(f"\\{cmd}{{{_esc(_translated(node, node.title, target_lang))}}}\n")
        if recurse:
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
            # Position and typography, not just the words: a caption sits
            # centered under its table/figure in the source, in whatever
            # font the source actually printed it in (kept on
            # visual_layout.style through reclassification - RFC 0001 §2.3 -
            # but unused here until now).
            vl = getattr(node, "visual_layout", None)
            style = getattr(vl, "style", None) if vl else None
            font_cmd = ""
            if style and style.font_size_pt:
                size = style.font_size_pt
                font_cmd = f"\\fontsize{{{size:.1f}}}{{{size * 1.2:.1f}}}\\selectfont "
            weight = "\\bfseries " if style and style.is_bold else ""
            body.append(
                "\\begin{center}\n"
                f"{{{font_cmd}{weight}\\textit{{{cap}}}}}\n"
                "\\end{center}\n\n"
            )
    elif isinstance(node, FootnoteBlock):
        # We don't have inline references reliably; render as a plain
        # small-font \footnotetext at the current position so the note
        # itself is preserved even if the inline superscript is lost.
        text = _esc(_translated(node, node.text, target_lang))
        marker = _esc(node.marker) if node.marker else ""
        body.append(
            f"\\par\\noindent{{\\footnotesize {marker} {text}}}\\par\n"
        )
    elif isinstance(node, CalloutBlock):
        label = _esc(_translated(node, node.label or node.kind.title(), target_lang))
        body.append("\\begin{mdframed}\n")
        if label:
            body.append(f"\\textbf{{{label}}}\\\\[0.2em]\n")
        for child in node.content:
            render(child, depth + 1)
        body.append("\\end{mdframed}\n")
    elif isinstance(node, FormulaBlock):
        # Prefer real LaTeX if a vision agent replaced the fallback. Model
        # output goes in unescaped, so filter file/IO primitives first.
        latex = _sanitize_latex_fragment((node.latex_expression or "").strip())
        md = getattr(node, "metadata", None) or {}
        has_real_latex = not md.get("needs_vision_ocr", False)
        if has_real_latex and latex:
            if node.is_numbered:
                tag = _esc(node.formula_number or "")
                body.append(f"\\begin{{equation}}\\tag{{{tag}}}\n{latex}\n\\end{{equation}}\n")
            else:
                body.append(f"\\[\n{latex}\n\\]\n")
        elif latex:
            # OCR fallback — no guarantee the text is valid LaTeX. Wrap
            # as \text{} inside display math so xelatex doesn't blow up.
            safe = _esc(latex)
            if node.is_numbered:
                tag = _esc(node.formula_number or "")
                body.append(f"\\begin{{equation}}\\tag{{{tag}}}\n\\text{{{safe}}}\n\\end{{equation}}\n")
            else:
                body.append(f"\\[\n\\text{{{safe}}}\n\\]\n")
    elif isinstance(node, TocEntryBlock):
        num = _esc(node.chapter_number or "")
        title = _esc(_translated(node, node.entry_text, target_lang))
        page = _esc(node.page_label) if node.page_label else (
            str(node.target_page + 1) if isinstance(node.target_page, int) else ""
        )
        left = f"{num}~{title}" if num else title
        if page:
            body.append(
                f"\\noindent {left}\\dotfill {page}\\\\\n"
            )
        else:
            body.append(f"\\noindent {left}\\\\\n")
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
        # The linear builder has no image pipeline — page-aware assembly renders
        # the source region. Emit a valid framed placeholder with whatever
        # caption/alt text exists, not the broken "\begin{center}[figure]".
        cap = _esc(_translated(
            node,
            getattr(node, "caption_text", "") or node.alt_text or "",
            target_lang,
        ))
        body.append(
            f"\\begin{{center}}\n\\fbox{{\\textit{{[{cap or 'figure'}]}}}}\n"
            f"\\end{{center}}\n"
        )
    elif isinstance(node, EphemeraBlock):
        pass  # ephemera (headers/footers/pagenums) are intentionally omitted
    elif isinstance(node, AlgorithmBlock):
        name = _esc(node.algorithm_name) if node.algorithm_name else ""
        num = _esc(str(node.algorithm_number or ""))
        pseudo = _esc(node.pseudocode)
        body.append(f"\\begin{{framed}}\n\\textbf{{{num}. {name}}}\\\\\n{pseudo}\n\\end{{framed}}\n")
    elif isinstance(node, SidebarBlock):
        # Delegate nested blocks to the shared dispatcher instead of a second,
        # drifting renderer: the inline copy used ListBlock.ordered (no such
        # field — always itemize) and CodeBlock.code (it is code_text — the
        # verbatim came out empty), and ran ListItemBlock through _para_text
        # (it has .content, not .inlines — every item came out empty).
        body.append("\\begin{minipage}{0.35\\textwidth}\n")
        for child in node.content:
            render(child, depth + 1)
        body.append("\\end{minipage}\n")
    elif isinstance(node, IndexEntryBlock):
        refs = ", ".join(_esc(r) for r in node.page_refs) if node.page_refs else ""
        body.append(f"\\noindent {_esc(node.term)}\\dotfill {refs}\\\\\n")
    elif isinstance(node, ParagraphBlock):
        txt = _esc(_translated(node, _para_text(node), target_lang))
        if not txt:
            pass
        elif (node.metadata or {}).get("semantic_decorator") in (
            "theorem", "proof", "example", "remark", "definition",
        ):
            dec = node.metadata["semantic_decorator"]
            _ENV = {
                "theorem": {
                    "theorem": "theorem", "lemma": "lemma",
                    "corollary": "corollary", "proposition": "proposition",
                },
                "proof": "proof",
                "example": "exampleenv",
                "remark": "remark",
                "definition": "definitionenv",
            }
            if dec == "theorem":
                stype = (node.metadata or {}).get("statement_type", "theorem")
                env = _ENV["theorem"].get(stype, "theorem")
            elif dec == "proof":
                env = "proof"
            else:
                env = _ENV.get(dec, dec)
            body.append(f"\\begin{{{env}}}\n{txt}\n\\end{{{env}}}\n")
        else:
            body.append(_wrap_align(txt, _alignment(node)) + "\n")


_COLUMN_X_TOLERANCE = 0.03


_SIZE_NOISE_TOLERANCE = 0.12  # within this of the table's median size = same size


def _snap_size(size_pt: float, median_pt: float) -> float:
    """Pull a cell's measured size onto the table's median when it is noise.

    The sizes come from measuring source spans, and that measurement is
    noisy: on the voltage-regulator fixture the cells of one visually
    uniform table span 3.12pt to 5.12pt, and setting each cell literally
    made the page ragged - "K 15 W" and "vqut" stood out from neighbours
    that are the same size in print. A real size difference in a table (a
    header set larger than its body) is far bigger than that spread, so
    anything within a small fraction of the median is treated as the same
    size and anything beyond it is kept.
    """
    if median_pt <= 0 or size_pt <= 0:
        return size_pt
    if abs(size_pt - median_pt) <= median_pt * _SIZE_NOISE_TOLERANCE:
        return median_pt
    return size_pt


_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")


def _is_latin_only(text: str) -> bool:
    """True when text has no Cyrillic - safe to set in a Latin-only font.

    DejaVu Serif is the document's main font because the source is
    multilingual (polyglossia/russian, RFC 0021) and needs Cyrillic
    glyphs everywhere else in the document; Latin Modern Roman has none
    at all (confirmed directly: xelatex reports "Missing character" for
    every Cyrillic codepoint tried under it). A cell with no Cyrillic in
    it is never at risk from that gap, and the source page it came from
    was typeset in a Times-like serif, not DejaVu Serif's - a rebuilt
    table's own visual-overlay comparison showed visibly different
    glyph shapes as a direct result.
    """
    return bool(text) and not _CYRILLIC_RE.search(text)


def _styled_cell_text(cell: Any, text: str, median_pt: float = 0.0, raw: str = "") -> str:
    """Wrap a cell's escaped text in the typography the source printed it in.

    Every TableCell carries the StyleDescriptor read off its own source span
    (RFC 0002) - size, weight, slant and colour - and the renderer used to
    drop all of it, setting one median size for the whole table. That is the
    same defect as summarising borders at table level: the information is
    measured per cell and then thrown away at the last step.

    The wrapper is scoped to the cell by the braces the caller puts around
    it, so one heavy or coloured cell cannot leak into its neighbours.
    """
    if not text:
        return text
    vl = getattr(cell, "visual_layout", None)
    style = getattr(vl, "style", None) if vl else None

    font_prefix = "\\latinfont " if _is_latin_only(raw or text) else ""

    if style is None:
        return f"{font_prefix}{text}" if font_prefix else text

    prefix = font_prefix
    size_pt = _snap_size(getattr(style, "font_size_pt", 0.0) or 0.0, median_pt)
    if size_pt > 0:
        prefix += f"\\fontsize{{{size_pt:.2f}}}{{{size_pt * 1.2:.2f}}}\\selectfont "
    if getattr(style, "is_monospace", False):
        prefix += "\\ttfamily "
    if getattr(style, "is_bold", False):
        prefix += "\\bfseries "
    if getattr(style, "is_italic", False):
        prefix += "\\itshape "

    body = f"{prefix}{text}" if prefix else text

    colour = getattr(style, "text_color_rgb", None)
    if colour and tuple(colour) != (0, 0, 0):
        r, g, b = (max(0, min(255, int(c))) for c in colour)
        body = f"\\textcolor[RGB]{{{r},{g},{b}}}{{{body}}}"

    fill = getattr(style, "background_color_rgb", None)
    if fill:
        r, g, b = (max(0, min(255, int(c))) for c in fill)
        # \cellcolor has to come first in the cell, before any content.
        body = f"\\cellcolor[RGB]{{{r},{g},{b}}}{body}"
    return body


def _cell_text(cell: Any) -> str:
    parts = [
        _para_text(content)
        for content in getattr(cell, "content", [])
        if isinstance(content, ParagraphBlock)
    ]
    return "\n".join(parts)


def _latex_linebreaks(escaped_text: str) -> str:
    """Turn a cell's internal "\n" separators (multiple source lines folded
    into one cell - a real rowspan, or lines merged across row-groups by
    _merge_orphan_rows) into LaTeX line breaks.

    Run AFTER _esc() so the literal backslash a real line break needs is
    never itself escaped. "\\\\ " (not bare "\\\\") keeps LaTeX from reading
    the next line's first token as an optional vertical-space argument to
    \\\\. Inside a p{} column this breaks the line within that cell, not the
    table row - \\\\'s row-ending meaning only applies at the tabular's own
    top level, not inside a nested parbox.
    """
    return escaped_text.replace("\n", "\\\\ ")


def _cell_x0(cell: Any) -> Optional[float]:
    vl = getattr(cell, "visual_layout", None)
    box = getattr(vl, "bounding_box", None) if vl else None
    return box.x0 if box is not None else None


def _cell_x1(cell: Any) -> Optional[float]:
    vl = getattr(cell, "visual_layout", None)
    box = getattr(vl, "bounding_box", None) if vl else None
    return box.x1 if box is not None else None


def _column_bins(grid: List[List[Any]]) -> Optional[List[float]]:
    """Canonical column x0 positions, or None if any cell lacks geometry.

    A row missing a middle column (a real gap in the source, not every row
    of a table has every field) is jagged in `grid` - shorter than the
    widest row, with nothing to say which column it's short in. Without
    this, padding a short row at its end shifts every later cell one column
    left of where it belongs. Clustering every cell's own x0 (kept on
    TableCell.visual_layout since src/analyzers/table/rules.py stopped
    discarding it) recovers which column each cell actually belongs to.

    The header row is the one row a real table always has exactly one cell
    per real column in - a value cell's x0 drifts with its own digit count
    and right/left alignment (a 1-digit "V" and a 3-digit "120" in the same
    UNITS-adjacent column do not share an x0), which is measurement noise,
    not a new column. Accumulating bins from every cell in the grid lets
    that noise cascade: a string of small sub-tolerance gaps in the value
    columns walks the running bin edge far enough from its start that a
    later, still-adjacent value gets read as its own column - measured on
    the voltage-regulator fixture, this split 6 real columns into 8.
    Anchoring on the header's own x0s (when it looks like a real header:
    more than one cell) sidesteps that drift entirely, since every other
    row already snaps each cell to its NEAREST bin by x0 (see the
    `_render_table` call site), not to where that row's own values happen
    to fall.
    """
    header = grid[0] if grid else []
    if len(header) > 1:
        header_x0s = [_cell_x0(cell) for cell in header]
        if all(x0 is not None for x0 in header_x0s):
            return sorted(header_x0s)

    x0s = []
    for row in grid:
        for cell in row:
            x0 = _cell_x0(cell)
            if x0 is None:
                return None
            x0s.append(x0)
    x0s.sort()
    bins: List[float] = []
    for x in x0s:
        if bins and x - bins[-1] < _COLUMN_X_TOLERANCE:
            continue
        bins.append(x)
    return bins


def _render_table(table: TableBlock) -> str:
    """Render a table atomically (RFC 0007 §5.2).

    If a table agent (GOT-OCR/MinerU) recognized it, use that LaTeX verbatim;
    otherwise fall back to the spatial grid from TableDetector.
    """
    md = getattr(table, "metadata", None) or {}
    recognized = md.get("latex")
    if recognized:
        safe = _sanitize_latex_fragment(recognized)
        return "\\begin{center}\n" + safe + "\n\\end{center}\n"
    grid = getattr(table, "grid", None)
    if not grid:
        return ""

    # The table's own median cell size, needed before the cells are built:
    # each cell is set at its own measured size, snapped onto this median
    # when the difference is only measurement noise (_snap_size).
    _sizes = sorted(
        cell.visual_layout.style.font_size_pt
        for row in grid for cell in row
        if cell.visual_layout
        and cell.visual_layout.style
        and cell.visual_layout.style.font_size_pt
    )
    median_pt = _sizes[len(_sizes) // 2] if _sizes else 0.0

    bins = _column_bins(grid)
    span_map = getattr(table, "span_map", {})
    # Populated below only when bins are available (real per-column source
    # geometry); stays None otherwise so the fallback path further down
    # knows to fall back to the old content-length-driven estimate.
    col_min_x0: Optional[List[Optional[float]]] = None
    col_max_x1: Optional[List[Optional[float]]] = None
    col_x0_sum: Optional[List[float]] = None
    col_x1_sum: Optional[List[float]] = None
    col_count: Optional[List[int]] = None
    # Row-span width, in characters, tracked per cell alongside its text -
    # needed below to give \multirow an explicit column width instead of
    # "*" (natural width), which a p{} column can't provide on its own.
    if bins is not None and len(bins) > 1:
        ncols = len(bins)
        rendered_rows = []
        # Real per-column width, in source page-width fractions: the widest
        # extent ANY cell in this column reaches, header included - not
        # the gap between two adjacent headers' own x0s (tried first, and
        # wrong whenever a header label is itself wider than the data
        # under it: "Decimal" over single-digit values measured a narrower
        # gap than "Decimal" itself needs, overflowing the column). This
        # is measured directly from the source geometry every cell already
        # carries, so it can't fall short of what actually has to fit.
        col_min_x0 = [None] * ncols
        col_max_x1 = [None] * ncols
        # Typical (mean) position, not the extremes above - needed to tell
        # whether a column's content hugs its LEFT drawn edge (a binary
        # code, conventionally left-set) or its RIGHT one (a number,
        # conventionally right-set): whichever side has the smaller
        # average padding from that column's own rule boundary.
        col_x0_sum = [0.0] * ncols
        col_x1_sum = [0.0] * ncols
        col_count = [0] * ncols
        for row_idx, row in enumerate(grid):
            cells = [""] * ncols
            texts = [""] * ncols
            for cell in row:
                x0 = _cell_x0(cell)
                col = min(range(ncols), key=lambda i: abs(bins[i] - x0))
                x1 = _cell_x1(cell)
                if x0 is not None:
                    col_min_x0[col] = x0 if col_min_x0[col] is None else min(col_min_x0[col], x0)
                    col_x0_sum[col] += x0
                    col_count[col] += 1
                if x1 is not None:
                    col_max_x1[col] = x1 if col_max_x1[col] is None else max(col_max_x1[col], x1)
                    col_x1_sum[col] += x1
                raw = _cell_text(cell)
                # texts[] keeps the RAW string: column widths are measured
                # from it below, and font commands are not content.
                text = _styled_cell_text(cell, _esc(raw).replace("\n", " "), median_pt, raw=raw)
                texts[col] = raw
                row_span = getattr(cell, "row_span", 1) or 1
                col_span = getattr(cell, "col_span", 1) or 1

                # Build cell tuple with spans and track spanned positions
                cell_content = text
                if row_span > 1 or col_span > 1:
                    cell_content = ("cell", row_span, col_span, text)
                cells[col] = cell_content

                # Populate span_map for positions occupied by this cell
                for r in range(row_idx, min(row_idx + row_span, len(grid))):
                    for c in range(col, min(col + col_span, ncols)):
                        if (r, c) != (row_idx, col):  # Don't map origin to itself
                            span_map[(r, c)] = (row_idx, col)
            rendered_rows.append((cells, texts))
    else:
        ncols = max((len(row) for row in grid), default=0)
        if ncols == 0:
            return ""
        rendered_rows = []
        for row_idx, row in enumerate(grid):
            styled = [
                _styled_cell_text(
                    cell, _esc(_cell_text(cell)).replace("\n", " "), median_pt, raw=_cell_text(cell)
                )
                for cell in row
            ]
            raws = [_cell_text(cell) for cell in row]
            styled += [""] * (ncols - len(styled))
            raws += [""] * (ncols - len(raws))

            # Build styled cells with span info
            styled_with_spans = []
            for col, cell in enumerate(row):
                row_span = getattr(cell, "row_span", 1) or 1
                col_span = getattr(cell, "col_span", 1) or 1
                if row_span > 1 or col_span > 1:
                    styled_with_spans.append(("cell", row_span, col_span, styled[col]))
                    # Populate span_map
                    for r in range(row_idx, min(row_idx + row_span, len(grid))):
                        for c in range(col, min(col + col_span, ncols)):
                            if (r, c) != (row_idx, col):
                                span_map[(r, c)] = (row_idx, col)
                else:
                    styled_with_spans.append(styled[col])
            styled_with_spans += [""] * (ncols - len(styled_with_spans))
            rendered_rows.append((styled_with_spans, raws))

    # A column holding whole condition sentences ("145V < VIN < 30V") needs
    # to wrap onto several lines to stay readable at a normal font size; a
    # column of short values (MIN/TYP/MAX/UNITS, single words or numbers)
    # reads better fixed-width and unwrapped. Column width in characters -
    # not a fixed column-index guess - decides which is which, since a
    # source table's column order isn't fixed across fixtures.
    col_max_len = [0] * ncols
    for _, texts in rendered_rows:
        for i, t in enumerate(texts):
            col_max_len[i] = max(col_max_len[i], len(t))

    _WIDE_CHAR_THRESHOLD = 14
    is_wide = [n > _WIDE_CHAR_THRESHOLD for n in col_max_len]
    # RFC 0021 SS3: a4paper with 2.2cm margins leaves ~16.6cm of \textwidth;
    # 16cm stays safely inside it once the table's own vertical rules are
    # accounted for. That upper bound is a SAFETY CAP, not the table's
    # actual target width: always filling it regardless of how wide the
    # source printed the table made every rebuilt table wider, proportionally
    # to its own page, than its source - a visual-overlay comparison
    # (tests/e2e/test_visual_overlay.py) measured the voltage-regulator
    # fixture's rebuilt table 31% wider than its source crop's own
    # proportions, which by itself was enough to misalign every row's ink
    # after both crops are normalized to a common size for comparison.
    # table.visual_layout.bounding_box carries the fraction of the SOURCE
    # page's own full width the table actually occupied there (RFC 0002);
    # scaling by the SAME fraction of a full a4 page's width reproduces that
    # proportion instead of always spending the whole safe budget.
    _A4_FULL_WIDTH_CM = 21.0
    _MAX_TABLE_WIDTH_CM = 16.0
    _MIN_TABLE_WIDTH_CM = 6.0
    vl = getattr(table, "visual_layout", None)
    bb = getattr(vl, "bounding_box", None) if vl else None
    if bb is not None:
        target_width_cm = max(
            _MIN_TABLE_WIDTH_CM,
            min(_MAX_TABLE_WIDTH_CM, (bb.x1 - bb.x0) * _A4_FULL_WIDTH_CM),
        )
    else:
        target_width_cm = _MAX_TABLE_WIDTH_CM
    _CHAR_WIDTH_CM = 0.17  # footnotesize average glyph advance, roughtly
    narrow_total_cm = sum(
        min(n, _WIDE_CHAR_THRESHOLD) * _CHAR_WIDTH_CM + 0.3
        for n, wide in zip(col_max_len, is_wide) if not wide
    )
    wide_count = sum(is_wide)
    wide_width_cm = (
        max(2.2, (target_width_cm - narrow_total_cm) / wide_count) if wide_count else 0.0
    )

    # A column's real width is where the source actually RULED it, not
    # where its own text happens to reach - a right-aligned "120" in a
    # column drawn 2cm wide only occupies that column's right half, so
    # measuring from glyphs alone (col_min_x0/col_max_x1, tried first)
    # systematically undersizes exactly that kind of column. rules.py's
    # _mark_cell_borders already finds every vertical rule the source
    # actually printed (reading the page's own pixels, since these
    # sources are scans with no vector strokes to read instead) and
    # keeps the ones strictly between the table's own left/right edges
    # as table.metadata["column_rule_x"] - the real boundary BETWEEN two
    # columns, independent of how far either one's own content reaches.
    col_width_cm: Optional[List[float]] = None
    # Which side of ITS OWN column a narrow column's content hugs - a
    # binary code ("00000000") sits flush against its column's LEFT
    # rule, a decimal number sits flush against its RIGHT one, and
    # "narrow column = right-align" (tried first, borrowed from how
    # MIN/TYP/MAX/UNITS behave) turned out not to hold for binary data:
    # confirmed on the decimal/binary fixture's own overlay, where a
    # blanket right-align shifted every "Binary" column's ink well past
    # where the source actually printed it. Read straight from the
    # SOURCE's own geometry per column - never assumed from what the
    # values look like - by comparing each column's average padding to
    # its own left vs right drawn boundary; whichever is smaller is the
    # edge the source set this column's text against.
    col_is_right: Optional[List[bool]] = None
    rule_x = (getattr(table, "metadata", None) or {}).get("column_rule_x")
    if bb is not None and rule_x and len(rule_x) == ncols - 1:
        boundaries = [bb.x0] + list(rule_x) + [bb.x1]
        fractions = [boundaries[i + 1] - boundaries[i] for i in range(ncols)]
        if all(f > 0 for f in fractions):
            # \tabcolsep (4pt, set below) pads BOTH sides of every p{}
            # column with space the declared width doesn't include -
            # confirmed by measuring the COMPILED PDF's own rule
            # positions directly: a column declared p{1.80cm} rendered
            # 59.4pt wide, not the 51.02pt asked for, an 8.4pt overshoot
            # matching 2*4pt almost exactly. Left uncorrected, each
            # internal boundary drifts further right than the one
            # before it - confirmed directly too, comparing real rule
            # positions in source vs compiled PDF as a fraction of the
            # table's own width: 4.8%/5.8%/7.0% off at the 1st/2nd/3rd
            # boundary, growing, not constant. Subtracting the known
            # overshoot from each column's OWN declared width (not from
            # a cumulative running boundary, which double-counts it -
            # that bug regressed an earlier attempt at this same fix)
            # keeps the actually-rendered width matching what was
            # measured from the source.
            # A flat 0.3cm floor here (tried first) is not tied to what
            # any COLUMN actually needs - confirmed directly on this
            # fixture's own overlay: subtracting tabcolsep left one
            # column narrower than its own "Decimal"/"Binary" header
            # text, and the header visibly overlapped its neighbor's
            # ("DecBinary", the two headers' ink literally overlaid).
            # The real per-column floor already exists for the fallback
            # path below (col_max_len chars * a font-scaled advance
            # width + padding) - reused here so subtracting tabcolsep
            # can never shrink a column past what ITS OWN longest cell
            # (header included, since col_max_len is measured over
            # every cell) needs.
            _TABCOLSEP_CM = 4.0 / 28.3465
            _char_width_scaled_cm = 0.17 * ((median_pt or 8.0) / 8.0)
            # The content floor only makes sense for a NARROW column -
            # one that renders unwrapped, so its width has to fit its
            # longest cell on one line. A WIDE column already wraps
            # (p{}), so col_max_len - a raw character count, with no
            # idea the cell will wrap - is not a real width requirement
            # for it: confirmed directly on the voltage-regulator
            # fixture, where merging a multi-line CONDITIONS cell
            # (_merge_orphan_rows) produced one long combined string,
            # and applying this floor to a WIDE column inflated it past
            # its own real rule-measured width (4.96cm declared vs a
            # source column that measures much narrower) - the opposite
            # of what subtracting tabcolsep was trying to fix.
            col_width_cm = [
                max(
                    col_max_len[i] * _char_width_scaled_cm + 0.3,
                    f * _A4_FULL_WIDTH_CM - 2 * _TABCOLSEP_CM,
                ) if not is_wide[i] else
                max(2.2, f * _A4_FULL_WIDTH_CM - 2 * _TABCOLSEP_CM)
                for i, f in enumerate(fractions)
            ]
            if col_x0_sum is not None and col_x1_sum is not None and col_count is not None:
                col_is_right = []
                for i in range(ncols):
                    if col_count[i] > 0:
                        avg_x0 = col_x0_sum[i] / col_count[i]
                        avg_x1 = col_x1_sum[i] / col_count[i]
                        pad_left = avg_x0 - boundaries[i]
                        pad_right = boundaries[i + 1] - avg_x1
                        col_is_right.append(pad_right < pad_left)
                    else:
                        col_is_right.append(True)

    # Fallback when the source printed no rules to read (a borderless
    # table) or the count doesn't line up with this table's own column
    # count: each column's own text extent, at least a defensive
    # content-length floor wide.
    if col_width_cm is None and col_min_x0 is not None and col_max_x1 is not None:
        fractions = [
            (col_max_x1[i] - col_min_x0[i])
            if col_min_x0[i] is not None and col_max_x1[i] is not None else None
            for i in range(ncols)
        ]
        if all(f is not None and f > 0 for f in fractions):
            col_width_cm = [
                max(f * _A4_FULL_WIDTH_CM, narrow_total_cm and (
                    min(col_max_len[i], _WIDE_CHAR_THRESHOLD) * _CHAR_WIDTH_CM + 0.3
                ))
                for i, f in enumerate(fractions)
            ]

    # Narrow columns hold short numeric-ish values (MIN/TYP/MAX/UNITS) that
    # the source right-aligns, not the wide CHARACTERISTICS/CONDITIONS text
    # columns (those stay p{}, left/paragraph-set as the source sets them).
    # Plain "r"/"l" (LaTeX auto-width) ignored the source's real column
    # width entirely; >{\raggedleft} (from \usepackage{array}, already in
    # the preamble) right-aligns within an explicit-width p{} column
    # instead, when a real measured width is available.
    def _narrow_align_prefix(i: int) -> str:
        return "" if col_is_right is not None and not col_is_right[i] else "\\raggedleft"

    if col_width_cm is not None:
        col_spec_parts = [
            f"p{{{col_width_cm[i]:.2f}cm}}" if wide
            else f">{{{_narrow_align_prefix(i)}}}p{{{col_width_cm[i]:.2f}cm}}"
            for i, wide in enumerate(is_wide)
        ]
    else:
        col_spec_parts = [
            f"p{{{wide_width_cm:.2f}cm}}" if wide else "r"
            for wide in is_wide
        ]
    # Borders come from the source, not from a house style: each cell
    # carries the edges the source actually printed a rule on
    # (TableCell.border_*, set by src/analyzers/table/rules.py
    # _mark_cell_borders from the page's own pixels). A column is ruled
    # here when the cells in it say so, and a boundary the source left
    # unruled stays unruled. With no borders detected at all, fall back to
    # a plain framed grid rather than inventing a look the source may not
    # have.
    def _cells_at(col: int) -> List[Any]:
        return [row[col] for row in grid if col < len(row)]

    def _any_border(cells: List[Any], side: str) -> bool:
        return any(getattr(c, side, False) for c in cells)

    has_any_border = any(
        getattr(cell, side, False)
        for row in grid for cell in row
        for side in ("border_left", "border_right", "border_top", "border_bottom")
    )

    if has_any_border and bins is not None and len(bins) == ncols:
        # ncols + 1 separators: the table's left edge, each internal
        # boundary, and the right edge. An internal boundary is ruled when
        # the column on either side of it carries that edge.
        seps = []
        for boundary in range(ncols + 1):
            left = _cells_at(boundary - 1) if boundary > 0 else []
            right = _cells_at(boundary) if boundary < ncols else []
            ruled = _any_border(left, "border_right") or _any_border(right, "border_left")
            seps.append("|" if ruled else "")
        col_spec = seps[0] + "".join(
            part + seps[i + 1] for i, part in enumerate(col_spec_parts)
        )
    else:
        col_spec = "|" + "|".join(col_spec_parts) + "|"

    def _render_cell(cell: Any, col: int) -> str:
        if isinstance(cell, tuple):
            _, row_span, col_span, text = cell
            if col_span > 1:
                # \multicolumn{N}{spec}{...} takes exactly ONE column-spec
                # for the merged cell as a whole - concatenating one spec
                # per spanned column ("ll" for col_span=2) is not valid
                # LaTeX ("Only one column-spec. allowed.") and halts the
                # whole compile. Size the merged cell to the real combined
                # width of the columns it spans when known (col_width_cm),
                # falling back to the is_wide-driven budget otherwise; a
                # spanned narrow column still needs the same per-column
                # alignment as col_spec_parts above (a binary code's own
                # column stays left-set, a number's stays right-set).
                spanned = range(col, min(col + col_span, len(is_wide)))
                if col_width_cm is not None:
                    combined_cm = sum(col_width_cm[c] for c in spanned)
                    spec = (
                        f"p{{{combined_cm:.2f}cm}}" if any(is_wide[c] for c in spanned)
                        else f">{{{_narrow_align_prefix(col)}}}p{{{combined_cm:.2f}cm}}"
                    )
                elif any(is_wide[c] for c in spanned):
                    spec = f"p{{{wide_width_cm * col_span:.2f}cm}}"
                else:
                    spec = "r"
            elif col_width_cm is not None:
                spec = (
                    f"p{{{col_width_cm[col]:.2f}cm}}" if is_wide[col]
                    else f">{{{_narrow_align_prefix(col)}}}p{{{col_width_cm[col]:.2f}cm}}"
                )
            else:
                spec = (f"p{{{wide_width_cm:.2f}cm}}" if is_wide[col] else "r")

            if row_span > 1:
                if col_width_cm is not None:
                    width = f"{col_width_cm[col]:.2f}cm"
                else:
                    width = f"{wide_width_cm:.2f}cm" if is_wide[col] else "*"
                if col_span > 1:
                    # Both row_span and col_span: \multicolumn{\multirow{...}{...}{...}}
                    return f"\\multicolumn{{{col_span}}}{{|{spec}|}}{{\\multirow{{{row_span}}}{{{width}}}{{{text}}}}}"
                else:
                    return f"\\multirow{{{row_span}}}{{{width}}}{{{text}}}"
            else:
                if col_span > 1:
                    return f"\\multicolumn{{{col_span}}}{{|{spec}|}}{{{text}}}"
                return text
        return cell  # Not a span tuple, render as-is

    # Which rows carry a rule is the source's decision too, and it is the
    # cells that hold it. An earlier version hardcoded "frame plus a rule
    # under the header, never between rows" on the claim that printed
    # tables of this kind are ruled that way - measuring the fixtures
    # disproved it: the decimal/binary page is ruled that way, but the
    # voltage-regulator page rules under every single row.
    def _row_ruled_below(index: int) -> bool:
        below = grid[index + 1] if index + 1 < len(grid) else []
        return _any_border(grid[index], "border_bottom") or _any_border(below, "border_top")

    # Per-row height correction via \rule{}{}  struts was tried here in two
    # independent forms - correcting only the tallest outlier row against
    # the table's median row height, and correcting every row against the
    # table's shortest row - and BOTH measured WORSE on the visual-overlay
    # test than doing nothing (~26.2% either way, up from the 24.5%
    # baseline without any height correction). Two differently-reasoned
    # attempts regressing by the same margin is evidence against the
    # technique itself in this measurement pipeline, not against either
    # attempt's specific choice of baseline - not attempted further here.
    body_lines = [f"\\begin{{tabular}}{{{col_spec}}}"]
    if has_any_border and grid and _any_border(grid[0], "border_top"):
        body_lines.append("\\hline")

    # Each row's real height, from the same per-cell geometry used for
    # column measurement above (min y0 to max y1 across that row's own
    # cells) - not assumed uniform, which \arraystretch's single constant
    # forces every row into regardless of whether the source's own line
    # was one row-band tall or three (confirmed on the voltage-regulator
    # overlay: every row measured the SAME 7.94pt height there, and on
    # this fixture's own overlay, rows drift steadily further from
    # source the further down the table they are - a uniform-height
    # renderer accumulating error one row at a time). Distributing extra
    # \\[space] AFTER a row that measured taller than the table's own
    # baseline (its shortest row - nothing prints shorter than one line)
    # - not a \rule strut BEFORE the row's content, tried twice before
    # and regressed the overlay test both times - lets a genuinely
    # multi-line row claim the height its own content needs without
    # forcing every other row to match it.
    def _row_height_fraction(row: List[Any]) -> Optional[float]:
        y0s, y1s = [], []
        for cell in row:
            vl = getattr(cell, "visual_layout", None)
            cbb = getattr(vl, "bounding_box", None) if vl else None
            if cbb is not None:
                y0s.append(cbb.y0)
                y1s.append(cbb.y1)
        return (max(y1s) - min(y0s)) if y0s else None

    row_heights = [_row_height_fraction(row) for row in grid]
    _valid_rh = [h for h in row_heights if h is not None and h > 0]
    _baseline_rh = min(_valid_rh) if _valid_rh else None

    # \arraystretch was a fixed 1.15 for every table (measured once, on
    # fixtures with a particular font size and row density, then baked
    # in) - confirmed wrong for this fixture specifically: font 14.15pt
    # * 1.2 leading * 1.15 stretch = 19.53pt/row, but the source's own
    # bbox fits 23 rows into 350pt, 15.24pt/row - a fixed constant tuned
    # on one table's density has no reason to hold on another's. Solving
    # for the stretch that makes THIS table's own row count exactly fill
    # its own real height budget (target_height_cm, the same measurement
    # width already uses) replaces the constant with a per-table value.
    _A4_FULL_HEIGHT_CM = 29.7
    _ARRAYSTRETCH_DEFAULT = 1.15
    dynamic_arraystretch = _ARRAYSTRETCH_DEFAULT

    # A row isn't always one line tall before any stretch is applied -
    # _merge_orphan_rows folds several source lines into one cell, and
    # that combined text WRAPS inside its wide p{} column instead of
    # collapsing to one line. Confirmed directly on the voltage-
    # regulator fixture: the merged "Output Voltage" condition cell
    # renders as two separate physical lines (124.3-129.8pt, then
    # 134.3-139.7pt) in the compiled PDF. Treating every row as exactly
    # one line (tried first) understates how tall the UNSTRETCHED table
    # already is, so solving for arraystretch from that undercount
    # asks for MORE stretch than needed and the wrapped rows' own extra
    # lines add height on top that the formula never budgeted for -
    # confirmed too: a table using the one-line-per-row estimate still
    # rendered 10% taller than the source proportion it was solved for.
    # Estimating each wide cell's own wrap count from its real width
    # (already measured, col_width_cm) and taking the tallest cell in
    # each row gives a real per-row line count instead of assuming 1.
    def _row_line_count(row_idx: int) -> int:
        if col_width_cm is None or row_idx >= len(rendered_rows):
            return 1
        _, texts = rendered_rows[row_idx]
        best = 1
        for col, raw in enumerate(texts):
            if col < len(is_wide) and is_wide[col] and raw and col < len(col_width_cm):
                chars_per_line = max(1.0, col_width_cm[col] / max(_CHAR_WIDTH_CM, 0.01))
                lines = max(1, -(-len(raw) // int(chars_per_line)))
                best = max(best, lines)
        return best

    if bb is not None and rendered_rows:
        target_height_pt = (bb.y1 - bb.y0) * _A4_FULL_HEIGHT_CM * 28.3465
        total_lines = sum(_row_line_count(i) for i in range(len(rendered_rows)))
        unstretched_pt = total_lines * (median_pt or 8.0) * 1.2
        if unstretched_pt > 0:
            dynamic_arraystretch = max(0.8, min(1.5, target_height_pt / unstretched_pt))
    _base_line_pt = (median_pt or 8.0) * 1.2 * dynamic_arraystretch

    # Each row's raw extra (an unscaled ratio-based guess) summed across
    # every row overshot the table's own real total height by ~24% on
    # the decimal/binary fixture, confirmed by measuring the COMPILED
    # PDF's own first/last row y-positions against the source bbox's
    # proportional height - adding real space for a genuinely tall row
    # without any budget compounds into a table taller than the source
    # ever was, which is exactly an ACCUMULATING drift top to bottom,
    # not the constant offset a simple per-row fix would produce. The
    # fix is the same one target_width_cm already applies to width:
    # scale the raw extras so they SUM to the table's own real height
    # budget, not whatever raw per-row ratios happen to add up to.
    _A4_FULL_HEIGHT_CM = 29.7
    raw_extra_pt = [0.0] * len(row_heights)
    if _baseline_rh:
        for i, rh in enumerate(row_heights):
            if rh:
                ratio = rh / _baseline_rh
                if ratio > 1.15:
                    raw_extra_pt[i] = _base_line_pt * (ratio - 1.0)
    _raw_extra_total = sum(raw_extra_pt)
    _extra_scale = 1.0
    if _raw_extra_total > 0 and bb is not None:
        target_height_pt = (bb.y1 - bb.y0) * _A4_FULL_HEIGHT_CM * 28.3465
        natural_total_pt = len(rendered_rows) * _base_line_pt
        budget_pt = max(0.0, target_height_pt - natural_total_pt)
        _extra_scale = min(1.0, budget_pt / _raw_extra_total)

    for i, (cells, _) in enumerate(rendered_rows):
        if has_any_border:
            rule = "\\hline" if i < len(grid) and _row_ruled_below(i) else ""
        else:
            rule = "\\hline" if i in (0, len(rendered_rows) - 1) else ""
        # Skip positions occupied by spanned cells from previous rows
        rendered = []
        for col, c in enumerate(cells):
            if (i, col) not in span_map:  # Only render if not spanned from above
                rendered.append(_render_cell(c, col))
        extra = ""
        if i < len(raw_extra_pt) and raw_extra_pt[i] > 0:
            extra = f"[{raw_extra_pt[i] * _extra_scale:.2f}pt]"
        # \tabularnewline, not bare "\\ " - a row ending in a p{} column
        # (every column can be p{} now that narrow columns get a measured
        # width too) can make a plain "\\" behave like the paragraph-
        # internal line break \raggedleft's own p{} box gives it rather
        # than the table's row separator; followed immediately by \hline
        # that surfaces as "Misplaced \noalign" and kills the compile.
        # \tabularnewline is array's own fix - unambiguously ends the ROW
        # regardless of what column type precedes it.
        body_lines.append(" & ".join(rendered) + f" \\tabularnewline{extra} " + rule)
    body_lines.append("\\end{tabular}")
    tabular = "\n".join(body_lines)

    # A fixed, readable font (footnotesize) with p{} wrapping on the wide
    # columns only, instead of \resizebox scaling the whole table down to
    # fit \textwidth - resizebox kept every column on one line but shrank a
    # wide, many-column table to a font too small to read, trading
    # structural fidelity for something no reader could use (RFC 0021 SS3
    # asks for a hybrid render that stays legible, not just geometrically
    # accurate).
    #
    # \arraystretch's default (1.0) packs rows tighter than a real printed
    # table's own leading - comparing a rebuilt table to its source page
    # (tests/e2e/test_visual_overlay.py) measured the source's row band
    # noticeably taller relative to the table's width than ours at 1.0,
    # even with every cell's text and position already exactly right.
    # Measured on the real fixtures in the locked Docker toolchain: 1.3
    # overshot past the source's own row-height/width ratio (it reads
    # looser than the source, not closer); 1.15 lands nearer the source's
    # measured proportions without guessing. \renewcommand here is scoped
    # to this \begin{center}...\end{center} group, not global.
    # Baseline size for anything the per-cell styling in _styled_cell_text
    # cannot set - a cell that reached here without a StyleDescriptor. The
    # median of the cells that do have one is the safe choice: one stray
    # span (a footnote marker, an OCR artifact) should not size the table.
    # The document default would be far off on its own - the decimal/binary
    # fixture is printed at ~14pt, and \footnotesize, which this used to
    # apply to the whole table, is ~8pt.
    size_pt = median_pt or 8.0
    size_cmd = f"\\fontsize{{{size_pt:.2f}}}{{{size_pt * 1.2:.2f}}}\\selectfont"

    # Keeps the column rules near the text without letting the glyphs touch
    # them. 2pt was tried and was too tight: "Decimal|Binary" came out with
    # the letters against the rule, worse than the source, which leaves a
    # visible gap. 4pt is the compromise - closer than LaTeX's 6pt default,
    # which pushed the rules well outside the span the text occupies.
    lines = [
        "\\begin{center}",
        f"\\renewcommand{{\\arraystretch}}{{{dynamic_arraystretch:.3f}}}",
        "\\setlength{\\tabcolsep}{4pt}",
        size_cmd,
        tabular,
        "\\end{center}",
        "",
    ]
    return "\n".join(lines)


SOURCE_DATE_EPOCH = 0  # 1970-01-01; fixed so rebuilds are byte-identical


def toolchain_fingerprint() -> str:
    """Identity of the TeX toolchain that compiled a build (RFC 0012 §3.3).

    The image installs TeX Live from apt without version pins, so an image built
    months apart can carry a different XeTeX. Recording the banner in kae.lock
    makes that visible instead of silently producing a different PDF.
    """
    try:
        proc = subprocess.run(
            ["xelatex", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"

    banner = (proc.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    return banner[0].strip() if banner else "unknown"


def compile_xelatex(
    tex_path: str, work_dir: str, source_date_epoch: int = SOURCE_DATE_EPOCH,
) -> str:
    """
    Compile a .tex file to PDF via XeLaTeX (RFC 0012 §3.3, runs in the locked
    Docker image with pinned TeX Live). Returns the PDF path. Two passes resolve
    the table of contents / references.

    SOURCE_DATE_EPOCH pins the timestamps XeTeX embeds as /CreationDate and
    /ModDate (and, with FORCE_SOURCE_DATE, the ones \\today expands to). Without
    it every rebuild produces a different PDF, so the output_hashes recorded in
    kae.lock would never reproduce (RFC 0021 §5.3).
    """
    get_security_manager().enforce(Capability.EXECUTE_LATEX_SANDBOX)

    base = os.path.splitext(os.path.basename(tex_path))[0]
    env = {
        **os.environ,
        "SOURCE_DATE_EPOCH": str(source_date_epoch),
        "FORCE_SOURCE_DATE": "1",
    }
    for _ in range(2):
        proc = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path],
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1800,
            env=env,
        )
    pdf_path = os.path.join(work_dir, f"{base}.pdf")
    if not os.path.exists(pdf_path):
        tail = proc.stdout.decode("utf-8", "replace")[-2000:] if proc.stdout else ""
        raise RuntimeError(f"XeLaTeX did not produce a PDF. Log tail:\n{tail}")
    return pdf_path
