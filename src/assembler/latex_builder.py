"""
LaTeX builder + XeLaTeX compiler for the target-document assembly layer.

Implements RFC 0021 (hybrid render) and RFC 0012 (XeLaTeX in locked Docker).
Reads the KRM tree — including visual_layout (bbox) and StyleDescriptor — and
emits a .tex document, then compiles it to PDF with XeLaTeX (Cyrillic-capable
via fontspec + polyglossia). Tombstoned nodes are skipped (RFC 0001 §2.4).
"""

import bisect
import logging
import os
import re
import statistics
import subprocess
from typing import Any, Dict, List, Optional, Tuple

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
    NormalizedRect,
    SidebarBlock,
    StyledTextSpan,
    TableBlock,
    TableCell,
    TextLineInline,
    TitlePageBlock,
    TocEntryBlock,
    VisualLayout,
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
% Its grotesque counterpart, a Helvetica clone, for a table the analyzer
% found printed in a sans-serif face (TableBlock.metadata["typeface"]).
\newfontfamily\latinsans{TeX Gyre Heros}
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
                size = _size_of(style)
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
# Same figure src/analyzers/table/rules.py's _ROW_Y_TOLERANCE uses to
# decide what shares one printed line. Kept in step with it on purpose:
# a cell further than this from its row's own baseline is, by that
# module's definition, not on the row's line - see _row_height_fraction.
_ROW_BASELINE_TOLERANCE = 0.003


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


def _styled_cell_text(
    cell: Any, text: str, median_pt: float = 0.0, raw: str = "", line_box: float = 0.0,
    leading_pt: float = 0.0, latin_font: str = "\\latinfont",
) -> str:
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

    font_prefix = f"{latin_font} " if _is_latin_only(raw or text) else ""

    if style is None:
        return f"{font_prefix}{text}" if font_prefix else text

    prefix = font_prefix
    size_pt = _snap_size(_size_of(style), median_pt)
    # A cell whose line box is the table's usual one was printed at the
    # table's usual size, whatever its text layer says, and so was one
    # whose ink is taller than the line its reported size would give: the
    # voltage-regulator fixture's "+25 C < Tj < +150 C" reads 3.12pt with
    # 5.9pt of glyphs, and was set at half its neighbours' width.
    h = _box_height(cell)
    if median_pt > 0 and line_box > 0 and h is not None and (
        abs(h - line_box) <= _SIZE_NOISE_TOLERANCE * line_box
        or h * _A4_HEIGHT_PT > 1.2 * _size_of(style)
    ):
        size_pt = median_pt
    if size_pt > 0:
        leading = leading_pt if leading_pt > 0 else size_pt * 1.2
        prefix += f"\\fontsize{{{size_pt:.2f}}}{{{leading:.2f}}}\\selectfont "
    if getattr(style, "is_monospace", False):
        prefix += "\\ttfamily "
    # A cell that says which of its words were bold sets those alone.
    if getattr(style, "is_bold", False) and not (getattr(cell, "metadata", None) or {}).get("line_bold"):
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


def _bold_marked(words: List[str], bold: List[bool]) -> str:
    """Escaped words, each run of bold ones set in \\textbf."""
    out, run = [], []
    for word, b in zip(words, bold + [False] * (len(words) - len(bold))):
        if b:
            run.append(_esc(word))
            continue
        if run:
            out.append("\\textbf{" + " ".join(run) + "}")
            run = []
        out.append(_esc(word))
    if run:
        out.append("\\textbf{" + " ".join(run) + "}")
    return " ".join(out)


def _line_texts(cell: Any, raw: str) -> List[str]:
    """A cell's lines, escaped, with the words the source printed bold set
    bold - where it says which those were (line_bold), else as they are."""
    lines = raw.split("\n")
    flags = (getattr(cell, "metadata", None) or {}).get("line_bold")
    if not flags or len(flags) != len(lines):
        return [_esc(line) for line in lines]
    return [_bold_marked(line.split(), f) for line, f in zip(lines, flags)]


def _positioned_lines(cell: Any, raw: str) -> str:
    """A stacked cell's lines with each run of words set where it was
    printed, or "" when the cell does not carry its runs.

    The pin description fixture nests a status table inside one cell -
    "IO/M  S1  S0  Status" over rows of figures - and set as plain lines
    its columns ran together at the left. Each run starts at its printed
    distance from the cell's left edge: the first held open by an invisible
    rule, each later one by boxing what comes before it to the printed
    distance between their starts, so our face's widths do not move it.
    """
    md = getattr(cell, "metadata", None) or {}
    segments = md.get("line_segments")
    box = getattr(getattr(cell, "visual_layout", None), "bounding_box", None)
    if not segments or box is None or len(segments) != raw.count("\n") + 1:
        return ""
    flags = md.get("line_bold") or []
    lines = []
    for n, runs in enumerate(segments):
        line_flags = flags[n] if n < len(flags) else []
        out = ""
        indent = (runs[0][0] - box.x0) * _A4_WIDTH_PT
        if indent > _PLACE_MIN_PT:
            out += f"\\rule{{{indent:.2f}pt}}{{0pt}}"
        used = 0
        for (x, text), nxt in zip(runs, runs[1:] + [None]):
            words = text.split()
            marked = _bold_marked(words, line_flags[used:used + len(words)])
            used += len(words)
            if nxt is None:
                out += marked
            else:
                out += f"\\makebox[{(nxt[0] - x) * _A4_WIDTH_PT:.2f}pt][l]{{{marked}}}"
        lines.append(out)
    return "\\newline ".join(lines)


def _cell_x0(cell: Any) -> Optional[float]:
    vl = getattr(cell, "visual_layout", None)
    box = getattr(vl, "bounding_box", None) if vl else None
    return box.x0 if box is not None else None


def _cell_x1(cell: Any) -> Optional[float]:
    vl = getattr(cell, "visual_layout", None)
    box = getattr(vl, "bounding_box", None) if vl else None
    return box.x1 if box is not None else None


# The share of a table's rows that must have a cell at an x for it to be
# a column of its own, where no header row says where the columns are.
_COLUMN_MIN_SUPPORT = 0.15


def _set_right(spans: List[Tuple[float, float]], x0s: List[float], x1s: List[float]) -> bool:
    """Whether a column's values are set flush right.

    Told by its values of other than the usual width: set right, theirs end
    where the column's others do and start where they may; set left, the
    other way about. Values all of one width - the index fixture's page
    numbers are nearly all two figures - agree at both edges and say
    nothing, and comparing all the edges' spreads let a point of OCR noise
    on their right edges turn the column left. Where fewer than two values
    stand out, the spreads decide."""
    if len(spans) >= 4:
        widths = sorted(x1 - x0 for x0, x1 in spans)
        usual = widths[len(widths) // 2]
        odd = [(x0, x1) for x0, x1 in spans if abs((x1 - x0) - usual) > 0.25 * usual]
        if len(odd) >= 2:
            mx0 = sorted(x0 for x0, _ in spans)[len(spans) // 2]
            mx1 = sorted(x1 for _, x1 in spans)[len(spans) // 2]
            off0 = sorted(abs(x0 - mx0) for x0, _ in odd)[len(odd) // 2]
            off1 = sorted(abs(x1 - mx1) for _, x1 in odd)[len(odd) // 2]
            return off1 < off0
    return _edge_spread(x1s) < _edge_spread(x0s)


def _edge_spread(xs: List[float]) -> float:
    """How far a column's edges disagree: their interquartile range."""
    q1, _, q3 = statistics.quantiles(xs, n=4)
    return q3 - q1


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
    # A column is where enough rows have a cell; a lone x0 is a stray, and
    # its cell belongs in the column nearest it. Without a header to anchor
    # on, every stray made a column: the index fixture's leftovers of OCR'd
    # leaders opened eight where it prints two.
    support = [0] * len(bins)
    for x in x0s:
        support[min(range(len(bins)), key=lambda k: abs(bins[k] - x))] += 1
    rows = sum(1 for row in grid if row)
    kept = [b for b, n in zip(bins, support) if n >= max(2, _COLUMN_MIN_SUPPORT * rows)]
    return kept if len(kept) >= 2 else bins


# TeX points per centimetre. A TeX "pt" is 1/72.27 in, not the PDF's
# 1/72 in (bp), and every length here is emitted as "pt": converting
# with the bp figure (_PT_PER_CM) made every emitted length 0.37% short of
# what was measured - 1.4pt over the decimal/binary fixture's 365pt,
# where its rows stepped 14.717 in the PDF against 14.773 intended.
_PT_PER_CM = 72.27 / 2.54

_A4_HEIGHT_PT = 29.7 * _PT_PER_CM
# A source's type sizes are PDF points (bp) and go out as TeX points too.
_TEX_PT_PER_BP = 72.27 / 72.0


def _size_of(style: Any) -> float:
    """A style's type size in TeX points (0 where it has none). Taken as
    is, a 9pt span went out 0.37% small, and a line of it that much
    short."""
    return (getattr(style, "font_size_pt", 0.0) or 0.0) * _TEX_PT_PER_BP
_A4_WIDTH_PT = 21.0 * _PT_PER_CM
# How far short of the table's edge a measured rule may stop and still be
# drawn across all of it: scan edges are ragged by a point or so.
_PARTIAL_RULE_TOL_PT = 2.0
# How far a column's set edge as the analyzer reads it off the ink lies
# from where LaTeX has to place the glyphs' box for the two inks to
# coincide: the glyphs' side bearing plus the anti-aliased edge the ink
# threshold leaves out. Measured, not derived - on the decimal/binary
# fixture every column sat 0.66pt too far in without it, and the
# voltage-regulator fixture's overlay is best at the same figure.
_INK_EDGE_INSET_PT = 0.7
# The narrowest p{} a narrow column is given, only so that a degenerate
# measurement cannot produce a zero or negative width.
_MIN_NARROW_P_CM = 0.1


def _wrapped_line_count(text: str, width_pt: float, size_pt: float, bold: bool) -> Optional[int]:
    """How many lines text breaks into at width_pt, from real glyph widths.

    Cells are set in TeX Gyre Termes, a Times clone, so the Times metrics
    PyMuPDF carries (tiro / tibo) are the widths xelatex will lay out.
    A flat average character width - the old estimate, 0.6em - is too
    wide for a Times face: it broke the voltage-regulator fixture's
    "Output Voltage" condition into two lines when it sets on one, and
    every height computed from that was 6.6pt out. Greedy word wrap, no
    hyphenation. None when the metrics are not available.
    """
    try:
        import pymupdf
    except ImportError:
        return None
    words = text.split()
    if not words or width_pt <= 0 or size_pt <= 0:
        return 1
    font = pymupdf.Font("tibo" if bold else "tiro")
    space = font.text_length(" ", fontsize=size_pt)
    lines, current = 1, 0.0
    for word in words:
        width = font.text_length(word, fontsize=size_pt)
        if current == 0.0:
            current = width
        elif current + space + width <= width_pt:
            current += space + width
        else:
            lines += 1
            current = width
    return lines


# How far a cell must sit from its column's set edge before it is drawn
# where it was printed: any distance for a heading or a placeholder mark
# (they never follow the values), more than a real indent for any other
# cell, so measurement noise does not move ordinary values.
_PLACE_EXPLICIT_PT = 0.1
_PLACE_INDENT_PT = 3.0
# The smallest printed indent of a run of words inside a cell worth setting.
_PLACE_MIN_PT = 0.2
# Capitals and ascenders of the faces tables are set in reach this share
# of the type size above the baseline; array's strut stands this share of
# a row's line above it.
_ASCENT = 0.7
# A dot leader's pitch, as \dotfill sets it.
_DOT_PITCH_EM = 0.44
_STRUT_HEIGHT = 0.7

# How far below its row's first line a one-line cell must have been
# printed before it is lowered to where it was printed, in the table's
# line boxes. A label centred on a block of sub-rows sits half a line or
# more down; OCR jitter within one printed line stays well under this.
_LOWER_MIN_BOX_SHARE = 0.45


def _box_height(cell: Any) -> Optional[float]:
    vl = getattr(cell, "visual_layout", None)
    box = getattr(vl, "bounding_box", None) if vl else None
    return box.y1 - box.y0 if box is not None else None


def _median_line_box(grid: List[List[Any]]) -> float:
    """The height of the table's usual one-line cell box, a page fraction.

    Line geometry is judged against this and not against a cell's own font
    size: the size comes from the OCR text layer and is noise on a scan
    (the voltage-regulator fixture's cells, uniform in print, read 3.1 to
    7.0pt), while every one of their boxes is the same 5.9pt tall."""
    heights = sorted(h for row in grid for cell in row if (h := _box_height(cell)))
    return heights[len(heights) // 2] if heights else 0.0


def _printed_on_one_line(cell: Any, line_box: float) -> bool:
    h = _box_height(cell)
    return h is not None and line_box > 0 and h <= 1.5 * line_box


def _first_line_centre(cell: Any, line_box: float) -> Optional[float]:
    """Where a cell's first printed line is centred, as a page fraction.

    None for a cell without geometry and for a placeholder mark, whose
    box is its dot's ink, not a line of text."""
    h = _box_height(cell)
    if h is None or line_box <= 0 or _cell_text(cell).strip() in _PLACEHOLDER_MARKS:
        return None
    return cell.visual_layout.bounding_box.y0 + min(h, line_box) / 2.0


def _lowered_to_print(text: str, cell: Any, row_top_line: Optional[float], line_box: float) -> str:
    """A one-line cell set as far below its row's first line as the source
    printed it.

    Every cell of a LaTeX row starts on the row's first line, while the
    source centres a label beside a block of sub-rows or stacked lines on
    that block: the voltage-regulator fixture's "Line Regulation" and its
    "Tj = 25 C" sit on the rule between their two condition sub-rows, and
    "Output Voltage" beside its three stacked conditions sits on the
    middle one. The shift is a \\raisebox with no height or depth, so the
    row keeps the height the rule solve gave it; a cell printed on more
    than one line is left to wrap.
    """
    centre = _first_line_centre(cell, line_box)
    if centre is None or row_top_line is None or not _printed_on_one_line(cell, line_box):
        return text
    if centre - row_top_line < _LOWER_MIN_BOX_SHARE * line_box:
        return text
    drop = (centre - row_top_line) * _A4_HEIGHT_PT
    return f"\\raisebox{{{-drop:.2f}pt}}[0pt][0pt]{{{text}}}"


# A lone mark standing in for a missing value, not a value itself.
_PLACEHOLDER_MARKS = {"\u2022", "\u00b7", "\u2219"}


def _grid_with_placeholder_marks(table: TableBlock) -> List[List[Any]]:
    """The table's grid with the placeholder marks found in its source's
    pixels set into their empty cells - for drawing only.

    The KRM grid holds the table's text as the source's text layer
    carries it; a scan's OCR misses lone dots (the decimal/binary fixture
    prints eleven "•" and its text layer has five), so the analyzer finds
    the rest in the pixels and records them in
    table.metadata["placeholder_marks"] instead of the grid. They are
    drawn here as ordinary cells, styled like their row, so every column
    and row measurement below treats them exactly as the dots OCR did
    read. The KRM itself is never modified.
    """
    grid = getattr(table, "grid", None)
    marks = (getattr(table, "metadata", None) or {}).get("placeholder_marks") or []
    if not grid or not marks:
        return grid
    rows = [list(row) for row in grid]
    for mark in marks:
        r = mark.get("row")
        if r is None or not 0 <= r < len(rows):
            continue
        x0, y0, x1, y1 = mark["bbox"]
        like = next((c for c in rows[r] if getattr(c, "visual_layout", None) is not None), None)
        rows[r].append(TableCell(
            content=[ParagraphBlock(inlines=[TextLineInline(spans=[StyledTextSpan(text="\u2022")])])],
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(x0=x0, y0=y0, x1=x1, y1=y1),
                page_or_screen_index=like.visual_layout.page_or_screen_index if like else 0,
                style=like.visual_layout.style if like else None,
            ),
        ))
        rows[r].sort(key=lambda c: _cell_x0(c) or 0.0)
    return rows


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
    grid = _grid_with_placeholder_marks(table)
    _latin_font = "\\latinsans" if md.get("typeface") == "sans" else "\\latinfont"
    if not grid:
        return ""

    # The table's own median cell size, needed before the cells are built:
    # each cell is set at its own measured size, snapped onto this median
    # when the difference is only measurement noise (_snap_size).
    _sizes = sorted(
        _size_of(cell.visual_layout.style)
        for row in grid for cell in row
        if cell.visual_layout
        and cell.visual_layout.style
        and cell.visual_layout.style.font_size_pt
    )
    median_pt = _sizes[len(_sizes) // 2] if _sizes else 0.0
    line_box = _median_line_box(grid)

    bins = _column_bins(grid)
    # Where the source's own column rules were measured, they are the
    # columns: a cell belongs to the band between two rules its centre lies
    # in. Snapping x0s to the header's instead sends a left-set paragraph
    # under a centred heading to the column before it - the pin description
    # fixture's "Name and Function" heading starts at 300pt, its paragraphs
    # at 171pt, nearer the 147pt "Type".
    _grid_rules = sorted((getattr(table, "metadata", None) or {}).get("column_rule_x") or [])
    if bins is not None and _grid_rules:
        _bb = table.visual_layout.bounding_box if table.visual_layout else None
        bins = [(_bb.x0 if _bb is not None else 0.0)] + _grid_rules

    def _column_index(cell: Any) -> int:
        x0, x1 = _cell_x0(cell), _cell_x1(cell)
        # A heading snapped onto its column keeps where it was printed in
        # printed_x; its box has been moved and no longer says.
        printed = (getattr(cell, "metadata", None) or {}).get("printed_x")
        if _grid_rules and printed:
            return sum(1 for r in _grid_rules if (printed[0] + printed[1]) / 2.0 > r)
        if _grid_rules and x0 is not None and x1 is not None:
            return sum(1 for r in _grid_rules if (x0 + x1) / 2.0 > r)
        return min(range(len(bins)), key=lambda i: abs(bins[i] - x0))

    # Boundaries a dot leader runs across: in a framed table with no rule
    # inside, between a column whose cells lead on and the next. They are
    # closed up (@{}), the next column's cell taking the leader on from its
    # left edge to its value - the index fixture's leaders reach each page
    # number as printed, where they stopped at the names' column with a
    # \tabcolsep of nothing either side and the number set off past it.
    _leader_joins = {
        _column_index(c) + 1 for row in grid for c in row if (c.metadata or {}).get("leader_after")
    } if (bins and ("table_rule_x0" in md or "table_rule_x1" in md)
          and not md.get("column_rule_x")) else set()
    _leader_joins = {b for b in _leader_joins if 0 < b < len(bins or [])}

    span_map = getattr(table, "span_map", {})
    # Where each lone placeholder mark sits in the source, by (row, col) -
    # see _place_at_printed_x below. Filled only where cells are binned by x.
    printed_x: Dict[Tuple[int, int], Tuple[float, float]] = {}
    # (row, col) of the cells the source printed on a single line, and of
    # those whose lines it printed stacked.
    one_line: set = set()
    stacked: set = set()
    # (row, col) of a stacked cell -> the pitch its lines were printed at.
    line_pitch: Dict[Tuple[int, int], float] = {}
    # Populated below only when bins are available (real per-column source
    # geometry); stays None otherwise so the fallback path further down
    # knows to fall back to the old content-length-driven estimate.
    col_min_x0: Optional[List[Optional[float]]] = None
    col_max_x1: Optional[List[Optional[float]]] = None
    col_x0_sum: Optional[List[float]] = None
    col_x1_sum: Optional[List[float]] = None
    col_count: Optional[List[int]] = None
    # Each column's usual left and right edge, the median of its cells'
    # boxes: what a cell's own box is compared with to place it.
    col_edge_x0: List[Optional[float]] = []
    col_edge_x1: List[Optional[float]] = []
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
        _col_x0s: List[List[float]] = [[] for _ in range(ncols)]
        _col_x1s: List[List[float]] = [[] for _ in range(ncols)]
        _col_spans: List[List[Tuple[float, float]]] = [[] for _ in range(ncols)]
        for row_idx, row in enumerate(grid):
            cells = [""] * ncols
            texts = [""] * ncols
            row_entries: Dict[int, List[Tuple[Any, Any, Any, str]]] = {}
            _row_lines = [c for c in (_first_line_centre(cell, line_box) for cell in row) if c is not None]
            for cell in row:
                if _printed_on_one_line(cell, line_box):
                    one_line.add((row_idx, _column_index(cell)))
            _row_top_line = min(_row_lines) if _row_lines else None
            for cell in row:
                x0 = _cell_x0(cell)
                col = _column_index(cell)
                x1 = _cell_x1(cell)
                # A column's usual edge is its values': not a heading's, not a
                # placeholder mark's (both placed on their own), and not a
                # box shared out of a longer line by character count.
                _measured = (
                    row_idx > 0
                    and not (cell.metadata or {}).get("x_estimated")
                    and _cell_text(cell).strip() not in _PLACEHOLDER_MARKS
                )
                if x0 is not None:
                    col_min_x0[col] = x0 if col_min_x0[col] is None else min(col_min_x0[col], x0)
                    col_x0_sum[col] += x0
                    if _measured:
                        _col_x0s[col].append(x0)
                    col_count[col] += 1
                if x1 is not None:
                    col_max_x1[col] = x1 if col_max_x1[col] is None else max(col_max_x1[col], x1)
                    col_x1_sum[col] += x1
                    if _measured:
                        _col_x1s[col].append(x1)
                        if x0 is not None:
                            _col_spans[col].append((x0, x1))
                raw = _cell_text(cell)
                # texts[] keeps the RAW string: column widths are measured
                # from it below, and font commands are not content.
                # Lines the source stacked in the cell stay stacked: the
                # voltage-regulator fixture prints "Output Voltage"'s three
                # conditions one under another, and joined into one line
                # they ran across half the column. Lines of a cell printed
                # on one line are only text the analyzer joined, and join.
                # \lineskiplimit lets \baselineskip alone space them: the
                # cell's first and last lines carry the row's stretched
                # struts, which otherwise push each line a strut apart
                # (8.8pt a line on that fixture, where it prints 7).
                # Stacked lines are spaced as the source spaced them: the
                # cell's box holds its lines' pitch, (height - one line) /
                # (lines - 1). At the face's own 1.2 of the size, the pin
                # description fixture's paragraphs ran 0.7pt a line taller
                # than print and the table 76pt past its page.
                _leading = 0.0
                if "\n" in raw and not _printed_on_one_line(cell, line_box):
                    stacked.add((row_idx, col))
                    body = "\\lineskiplimit=-\\maxdimen " + (
                        _positioned_lines(cell, raw) or "\\newline ".join(_line_texts(cell, raw))
                    )
                    _n = raw.count("\n") + 1
                    _h = _box_height(cell)
                    if _h is not None and _n > 1:
                        _leading = max(0.0, (_h - line_box) * _A4_HEIGHT_PT / (_n - 1))
                        line_pitch[(row_idx, col)] = _leading
                else:
                    body = " ".join(_line_texts(cell, raw))
                # A dot leader the source printed after this cell runs on to
                # the end of its column.
                if (cell.metadata or {}).get("leader_after"):
                    body += "\\dotfill"
                # ...and on through the next column to its value, across a
                # boundary closed up for it (_leader_joins).
                if col in _leader_joins and any(
                    (c.metadata or {}).get("leader_after") and _column_index(c) == col - 1 for c in row
                ):
                    body = "\\dotfill " + body
                text = _styled_cell_text(cell, body, median_pt, raw=raw, line_box=line_box,
                                         leading_pt=_leading, latin_font=_latin_font)
                if (getattr(cell, "row_span", 1) or 1) == 1:
                    text = _lowered_to_print(text, cell, _row_top_line, line_box)
                texts[col] = raw
                _printed = (getattr(cell, "metadata", None) or {}).get("printed_x")
                if _printed:
                    printed_x[(row_idx, col)] = (_printed[0], _printed[1], _PLACE_EXPLICIT_PT)
                elif raw.strip() in _PLACEHOLDER_MARKS and x0 is not None and x1 is not None:
                    printed_x[(row_idx, col)] = (x0, x1, _PLACE_EXPLICIT_PT)
                elif x0 is not None and x1 is not None and not (cell.metadata or {}).get("x_estimated"):
                    printed_x[(row_idx, col)] = (x0, x1, _PLACE_INDENT_PT)
                row_span = getattr(cell, "row_span", 1) or 1
                col_span = getattr(cell, "col_span", 1) or 1

                # Build cell tuple with spans and track spanned positions
                cell_content = text
                if row_span > 1 or col_span > 1:
                    cell_content = ("cell", row_span, col_span, text)
                # A collision here (cells[col] already set by an earlier
                # cell in THIS row, both nearest to the same bin) silently
                # overwrites rather than merges - confirmed a REAL case on
                # the voltage-regulator fixture: grid row 8 holds both
                # "Quiescent Current Change" (x0 nearest column 0) and
                # "with line" (x0 also nearest column 0, since it's
                # indented under the label rather than sitting in the
                # CONDITIONS column), and "with line" - processed second -
                # overwrites the row's own CHARACTERISTICS label entirely,
                # so it never appears in the rendered table at all.
                # Tried stacking both texts into one cell (a real \\ line
                # break, scoped to column 0 only - the same collision in
                # the CONDITIONS column, e.g. "Tj - 25*C" / "145V<VIN<30V"
                # on that fixture's "Line Regulation" row, already has a
                # working jagged-row convention that stacking breaks
                # instead), with the row's own line-count budget updated
                # to know about the forced break. Measured worse even so
                # (24.2% -> 26.6%): grid row 8 already merges two SOURCE
                # rows that print as visually distinct lines (confirmed:
                # source shows "Quiescent Current Change" on one line,
                # "with line" on the next, not stacked in one cell) - the
                # real bug is upstream, in whichever analyzer step grouped
                # those two source rows into one grid row to begin with,
                # not in how latex_builder renders whatever grid it's
                # given. Left as a real, confirmed defect (the label
                # currently vanishes) for that upstream investigation
                # rather than patched here where fixing it regresses the
                # very metric this file is measured against.
                #
                # Also tried tracking which rows hit this collision and
                # refusing to hand THEM extra vertical space later (their
                # row_heights span is contaminated by the overwritten
                # cell's own real bbox, so the ratio-based outlier checks
                # further down read them as taller than their rendered
                # content justifies) - measured WORSE on both the
                # official and a fair (no test-padding) comparison
                # (voltage-regulator: 25.2% -> 26.1%, 25.5% -> 27.8%).
                # Source really did print extra vertical space around
                # that row even though this rendering lost part of its
                # text, so refusing the height entirely just traded one
                # inaccuracy for a bigger one. Not attempted further.
                cells[col] = cell_content
                row_entries.setdefault(col, []).append((x0, x1, cell_content, raw))

                # Populate span_map for positions occupied by this cell
                for r in range(row_idx, min(row_idx + row_span, len(grid))):
                    for c in range(col, min(col + col_span, ncols)):
                        if (r, c) != (row_idx, col):  # Don't map origin to itself
                            span_map[(r, c)] = (row_idx, col)
            # Two cells of this row landing in one column are set SIDE BY
            # SIDE, each where it was printed - the voltage-regulator
            # fixture prints "Tj = 25 C" and its condition range next to
            # each other in the CONDITIONS column (x 322 and 355pt), and
            # the later one used to overwrite the earlier, which vanished
            # from the rendered table. Stacking them was tried and lost
            # (they are one printed line, not two); side by side, at
            # their printed gap, is how they were printed.
            for col, entries in row_entries.items():
                if len(entries) < 2 or any(e[0] is None or e[1] is None for e in entries):
                    continue
                # A spanning cell set beside another gives up its span: the
                # two share one cell of this row, and neither may be lost.
                if any(isinstance(e[2], tuple) for e in entries):
                    for key in [k for k, v in span_map.items() if v == (row_idx, col)]:
                        del span_map[key]
                entries = [(e[0], e[1], e[2][3] if isinstance(e[2], tuple) else e[2], e[3]) for e in entries]
                # Each one starts where it was printed: everything before it
                # is boxed to the printed distance between their starts.
                # Held apart by the printed gap instead, the second moved
                # with the first's width, and ours is not the print's - the
                # voltage-regulator fixture's "with line" sat 3.5pt left of
                # its print behind a narrower "Quiescent Current Change".
                entries.sort(key=lambda e: e[0])
                joined = ""
                for prev, cur in zip(entries, entries[1:]):
                    advance = max(0.0, (cur[0] - prev[0]) * _A4_WIDTH_PT)
                    joined += f"\\makebox[{advance:.2f}pt][l]{{{prev[2]}}}"
                joined += entries[-1][2]
                cells[col] = joined
                texts[col] = " ".join(e[3] for e in entries)
                printed_x[(row_idx, col)] = (entries[0][0], entries[-1][1], _PLACE_INDENT_PT)
            rendered_rows.append((cells, texts))
        col_edge_x0 = [sorted(v)[len(v) // 2] if v else None for v in _col_x0s]
        col_edge_x1 = [sorted(v)[len(v) // 2] if v else None for v in _col_x1s]
    else:
        ncols = max((len(row) for row in grid), default=0)
        if ncols == 0:
            return ""
        rendered_rows = []
        for row_idx, row in enumerate(grid):
            styled = [
                _styled_cell_text(
                    cell, _esc(_cell_text(cell)).replace("\n", " "), median_pt, raw=_cell_text(cell),
                    latin_font=_latin_font,
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
    # The column boundaries twice over: on the source page (page
    # fractions) and in the emitted tabular (TeX pt from its left edge).
    # Set only where the source's own rules gave the columns; used to
    # draw a rule that stops short of the table where the source's does.
    _source_bounds: Optional[List[float]] = None
    _emitted_bounds_pt: Optional[List[float]] = None
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
    # Per-column: does ONLY the header cell (row 0) sit centered over this
    # column, independent of how the data cells beneath it are set? See
    # the real check further down, inside the real-column-rule branch -
    # defaults to "no" everywhere else, since that check needs the same
    # real rule boundaries col_width_cm does.
    header_is_centered: List[bool] = [False] * ncols
    # \tabcolsep pads BOTH sides of every column with space the declared
    # width does not include, and a flat 4pt is simply wrong for a table
    # the source printed tighter than that. Measured per column as
    # (rule-to-rule width - the extent that column's own glyphs occupy),
    # the decimal/binary fixture's tightest column carries 3.1pt of real
    # padding in TOTAL - 1.6pt a side, where LaTeX was adding 8pt. That
    # column then cannot fit inside the width its own rules give it, and
    # the content floor below has to inflate it to compensate: exactly
    # what left it +6.2pt wider than the source ruled it, with the whole
    # table 4.2% too wide as a result. Derived from the source's own
    # geometry inside the real-rule branch below; stays 4pt when there is
    # no rule geometry to measure it from.
    _tabcolsep_pt = 4.0
    # Extra indent, per column, beyond what \tabcolsep already gives:
    # LaTeX sets a column's text exactly tabcolsep from its rule, while
    # a source indents each column by its own amount (measured on the
    # decimal/binary fixture: 5.2-8.2pt on whichever side each column is
    # set against). Filled from the analyzer's own pixel measurement
    # inside the real-rule branch below; zero everywhere else.
    _col_indent_pt = [0.0] * ncols
    _table_md = getattr(table, "metadata", None) or {}
    # The rules' printed weight, in TeX points (measured in PDF points).
    # LaTeX's own 0.4pt default when the source's was not measured.
    _rule_w_pt = (
        _table_md["rule_width_pt"] * 72.27 / 72.0
        if _table_md.get("rule_width_pt") else 0.4
    )
    rule_x = _table_md.get("column_rule_x")
    # A side the scan measured and found no frame rule on is bounded by
    # the text itself (bb.x0/bb.x1 below). Nothing pads it: LaTeX's
    # \tabcolsep there would push the outermost text off the edge the
    # source printed it on - measured on the voltage-regulator fixture,
    # which draws no frame, every rule landed 3-5pt off its source once
    # the table was cut to its text.
    _open_left = bool(rule_x) and _table_md.get("table_rule_x0") is None
    _open_right = bool(rule_x) and _table_md.get("table_rule_x1") is None
    if bb is not None and rule_x and len(rule_x) == ncols - 1:
        # Every INTERNAL boundary here is a rule the source actually
        # printed; the outer two used to come from bb.x0/bb.x1 instead -
        # the table's own bounding box, which is the union of its CELLS'
        # boxes, i.e. a TEXT extent. A column's glyphs never reach its
        # rule (a right-aligned number sits against one edge only), so
        # substituting the box for the outer rules put the entire error
        # on the first and last column while the internal ones stayed
        # accurate: measured on the decimal/binary fixture, 13.9pt of
        # real width missing on the left and 7.6pt on the right, against
        # 1.3pt or less on both internal columns. _mark_cell_borders
        # already detects those outer rules - it now keeps them too.
        # A table that draws no outer rules (the voltage-regulator
        # fixture prints none) still falls back to its box, unchanged.
        _outer_left = _table_md.get("table_rule_x0")
        _outer_right = _table_md.get("table_rule_x1")
        boundaries = (
            [_outer_left if _outer_left is not None else bb.x0]
            + list(rule_x)
            + [_outer_right if _outer_right is not None else bb.x1]
        )
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
            # The real padding the SOURCE printed around each column's
            # own text: that column's rule-to-rule width minus the extent
            # its glyphs actually occupy. Only columns bounded by real
            # rules on BOTH sides can be measured this way - where an
            # outer rule is missing the boundary came from the text box
            # itself, whose "padding" is zero by construction and would
            # drag this to nothing.
            _real_pads_pt: List[float] = []
            for _i in range(ncols):
                if _i == 0 and _outer_left is None:
                    continue
                if _i == ncols - 1 and _outer_right is None:
                    continue
                if (
                    col_min_x0 is None or col_max_x1 is None
                    or col_min_x0[_i] is None or col_max_x1[_i] is None
                ):
                    continue
                _pad_pt = (
                    fractions[_i] - (col_max_x1[_i] - col_min_x0[_i])
                ) * _A4_FULL_WIDTH_CM * _PT_PER_CM
                if _pad_pt > 0:
                    _real_pads_pt.append(_pad_pt)
            if _real_pads_pt:
                # Halved, since \tabcolsep applies to EACH side. Capped at
                # the old 4pt default so this can only ever tighten a
                # table, never loosen one past what was already measured
                # to work, and floored at 0.5pt so two columns' ink cannot
                # end up touching in a table the source printed with
                # almost no padding at all.
                _tabcolsep_pt = max(0.5, min(4.0, min(_real_pads_pt) / 2.0))
            _TABCOLSEP_CM = _tabcolsep_pt / _PT_PER_CM

            # No floor from the column's content: a column is as wide as
            # its rules say, and a cell wider than that is set where the
            # source set it - into the column's padding (_fit_to_column).
            # The voltage-regulator fixture prints "uV/VOUT" from right
            # against its UNITS rule, with no padding at all; a floor that
            # held the column open for it made the table 4.7pt wider than
            # its source and moved every rule off its source by as much.
            # Earlier attempts at narrowing these columns were judged on
            # an overlay that cut the rebuild with a margin the source
            # did not get, and are not evidence either way.
            # A column's advance is p{} + 2*tabcolsep + the RULE beside
            # it: LaTeX adds \arrayrulewidth (0.4pt by default, never set
            # here) for every "|" in the spec, and nothing above accounts
            # for it. The fractions come from rule centres, so the rules'
            # own width lands on top of the span they describe and the
            # error accumulates left to right - measured on the
            # decimal/binary fixture, its four verticals sat +0.7, +0.9,
            # +1.5 and +2.1pt out against the source's, about half a
            # point per column, with 5 rules x 0.4pt = 2.0pt of it.
            _ARRAYRULE_CM = _rule_w_pt / _PT_PER_CM

            def _sides_cm(i: int) -> float:
                """What column i's two sides add to its p{}: a \\tabcolsep
                and half a rule each, or nothing on an open side."""
                open_sides = (i == 0 and _open_left) + (i == ncols - 1 and _open_right)
                return (2 - open_sides) * (_TABCOLSEP_CM + _ARRAYRULE_CM / 2)

            col_width_cm = [
                max(
                    _MIN_NARROW_P_CM if not is_wide[i] else 2.2,
                    f * _A4_FULL_WIDTH_CM - _sides_cm(i),
                )
                for i, f in enumerate(fractions)
            ]
            # Rounded once, to what the column spec prints, so that
            # everything sized from these widths (a boxed cell, a partial
            # rule's position) agrees with the column LaTeX actually sets.
            col_width_cm = [round(w, 2) for w in col_width_cm]
            _source_bounds = boundaries
            _emitted_bounds_pt = [0.0 if _open_left else _rule_w_pt / 2.0]
            for i in range(ncols):
                _emitted_bounds_pt.append(
                    _emitted_bounds_pt[-1] + (col_width_cm[i] + _sides_cm(i)) * _PT_PER_CM
                )
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

            # What the source indents each column by, beyond what LaTeX
            # already sets between its boundary and its text. Taken from
            # the analyzer's own pixel measurement of where each column's
            # ink starts and ends (column_ink_x0/x1) - NOT from the KRM
            # cell boxes, which cannot answer this: measured against the
            # same pixels, a per-column median of those boxes is 33-39pt
            # off on a right-set column and negative on another, where some
            # cells' boxes cross a rule outright. It is measured on the
            # column's SET side, the one col_is_right names: taking
            # whichever side was nearer its rule picked the ragged side of
            # the voltage-regulator fixture's TYP and UNITS columns, whose
            # widest values nearly fill them, and gave them no indent.
            _ink_x0 = _table_md.get("column_ink_x0")
            _ink_x1 = _table_md.get("column_ink_x1")
            if _ink_x0 and _ink_x1 and len(_ink_x0) == ncols:
                for _i in range(ncols):
                    if _ink_x0[_i] is None or _ink_x1[_i] is None:
                        continue
                    _right_set = col_is_right[_i] if col_is_right is not None else True
                    _set_pt = (
                        boundaries[_i + 1] - _ink_x1[_i] if _right_set
                        else _ink_x0[_i] - boundaries[_i]
                    ) * _A4_FULL_WIDTH_CM * _PT_PER_CM
                    # \tabcolsep and half the rule, or nothing on an open
                    # side; and the inset between the ink edge as read and
                    # the glyph box LaTeX places (_INK_EDGE_INSET_PT).
                    _open = (_i == ncols - 1 and _open_right) if _right_set else (_i == 0 and _open_left)
                    _pad_pt = 0.0 if _open else _tabcolsep_pt + _rule_w_pt / 2.0
                    _col_indent_pt[_i] = max(0.0, _set_pt - (0.0 if _open else _pad_pt + _INK_EDGE_INSET_PT))

            # A column-group header ("CONDITIONS") can be CENTERED over its
            # own wide column even though every DATA cell below it sets
            # left (a binary code, a wrapped sentence) - confirmed directly
            # on the voltage-regulator fixture: "CONDITIONS"'s own x0 sits
            # at 0.6146 of the page, almost exactly the midpoint of its
            # column's real rule boundaries (0.5355-0.7534, center 0.6445)
            # minus half the word's own width, while "CHARACTERISTICS" (the
            # OTHER wide column) sits flush against ITS column's left rule
            # (pad_left = 0) - a genuine row-label column, not a centered
            # group heading. col_is_right above blends the header row's own
            # padding into the SAME average as all the data rows beneath
            # it (col_x0_sum/col_x1_sum accumulate every row including row
            # 0), so a lone centered header among many left-set data rows
            # never shows up there - it needs its own, row-0-only check:
            # padding roughly EQUAL on both sides (not flush against
            # either edge) is what "centered" actually looks like
            # geometrically, distinct from "left-set" or "right-set" where
            # one side's padding is near zero.
            if grid:
                for cell in grid[0]:
                    hx0 = _cell_x0(cell)
                    hx1 = _cell_x1(cell)
                    if hx0 is None or hx1 is None:
                        continue
                    hcol = _column_index(cell)
                    col_w = boundaries[hcol + 1] - boundaries[hcol]
                    if col_w <= 0:
                        continue
                    pad_left = hx0 - boundaries[hcol]
                    pad_right = boundaries[hcol + 1] - hx1
                    if (
                        min(pad_left, pad_right) > 0.15 * col_w
                        and abs(pad_left - pad_right) < 0.25 * col_w
                    ):
                        header_is_centered[hcol] = True

    def _text_start(i: int) -> Optional[float]:
        """Where column i's text starts on the source page: its values'
        usual left edge if it is set left, its widest value's if right."""
        left_set = col_is_right is not None and not col_is_right[i]
        if left_set and i < len(col_edge_x0) and col_edge_x0[i] is not None:
            return col_edge_x0[i]
        return col_min_x0[i]

    # Which side each column's values are set against, where no rules gave
    # it above: the side where their edges agree. Without it nothing in a
    # borderless table could be placed where it was printed - the index
    # fixture's sub-entries ("A XEROX CO.") sat flush with the names they
    # are indented under. The spread is the middle half's, so a few OCR
    # boxes swallowing a leader's dots do not turn a right-set column of
    # page numbers left.
    if col_is_right is None and col_x0_sum is not None:
        col_is_right = [
            _set_right(_col_spans[i], _col_x0s[i], _col_x1s[i])
            if len(_col_x0s[i]) >= 4 and len(_col_x1s[i]) >= 4 else False
            for i in range(ncols)
        ]

    # Fallback when the source printed no rules to read (a borderless
    # table) or the count doesn't line up with this table's own column
    # count: each column reaches from where its text starts to where the
    # next column's does, less the \tabcolsep either side of the gap, and
    # the last one over its own text; each at least a defensive
    # content-length floor wide. Not each column's own text extent: a
    # leader runs a column's text up to the next one's, and the index
    # fixture's two columns, measured so, came to 15cm where the source
    # printed 12cm, its page numbers pushed far out past the source's.
    # A left-set column's text starts at its values' usual edge - a cell
    # printed out past it is placed there on its own - and a right-set
    # one's where its widest value does.
    if col_width_cm is None and col_min_x0 is not None and col_max_x1 is not None:
        _gap = 2 * _tabcolsep_pt / (_A4_FULL_WIDTH_CM * _PT_PER_CM)
        _starts = [_text_start(i) for i in range(ncols)]
        fractions = [
            (col_max_x1[i] - _starts[i]) if i == ncols - 1
            else (_starts[i + 1] - _starts[i] - (0.0 if i + 1 in _leader_joins else _gap))
            if all(v is not None for v in (_starts[i], col_max_x1[i], _starts[min(i + 1, ncols - 1)]))
            else None
            for i in range(ncols)
        ]
        if all(f is not None and f > 0 for f in fractions):
            col_width_cm = [f * _A4_FULL_WIDTH_CM for f in fractions]

    # Narrow columns hold short numeric-ish values (MIN/TYP/MAX/UNITS) that
    # the source right-aligns, not the wide CHARACTERISTICS/CONDITIONS text
    # columns (those stay p{}, left/paragraph-set as the source sets them).
    # Plain "r"/"l" (LaTeX auto-width) ignored the source's real column
    # width entirely; >{\raggedleft} (from \usepackage{array}, already in
    # the preamble) right-aligns within an explicit-width p{} column
    # instead, when a real measured width is available.
    def _narrow_align_prefix(i: int) -> str:
        # \leftskip / \rightskip, not \hspace: both were measured on an
        # isolated table (tests/e2e/_debug_colindent_calib.py) and only
        # the skips do the job. A trailing <{\hspace{}} on a \raggedleft
        # column moved its text by exactly nothing (its gap to the rule
        # stayed 1.7pt whether the hspace was there or not), while
        # \rightskip moved it to 8.3pt as asked. \hspace also indents
        # only the FIRST line of a wrapped cell, where a skip indents
        # every line. Neither moves the column rules - confirmed
        # identical rule positions across all three variants, which
        # matters because those rules currently land within 0.6pt of
        # the source and must stay there.
        _left_set = col_is_right is not None and not col_is_right[i]
        _indent = _col_indent_pt[i] if i < len(_col_indent_pt) else 0.0
        if _left_set:
            return f"\\leftskip={_indent:.2f}pt" if _indent > 0.05 else ""
        return "\\raggedleft" + (
            f"\\rightskip={_indent:.2f}pt" if _indent > 0.05 else ""
        )

    if col_width_cm is not None:
        # A wide column is set ragged right like prose - unless its values
        # are set right, as the index fixture's page numbers are.
        col_spec_parts = [
            (f">{{\\raggedleft}}p{{{col_width_cm[i]:.2f}cm}}"
             if col_is_right is not None and col_is_right[i]
             else f"p{{{col_width_cm[i]:.2f}cm}}") if wide
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
        # The OUTER two separators come from the scan's own measurement
        # of the frame, not from a vote over the cells. _any_border is
        # any(), so one stray row whose edge cell picked up a border
        # turns the whole frame on: the voltage-regulator fixture draws
        # no left frame at all - the scan recorded no table_rule_x0 and
        # the header row's first cell agrees with border_left False -
        # yet we emitted "|" there, a rule 124pt left of the source's
        # leftmost, which is the entire -436px offset its border mask
        # showed. Trust this only where the scan actually ran:
        # column_rule_x present means it measured this table's
        # verticals and would have recorded a frame had one been drawn.
        if _table_md.get("column_rule_x"):
            seps[0] = "@{}" if _open_left else "|"
            seps[ncols] = "@{}" if _open_right else "|"
        elif "table_rule_x0" in _table_md or "table_rule_x1" in _table_md:
            # The scan measured a frame and no rule inside it. A cell's
            # border flags name the rules bounding its band - here the
            # frame's two sides - not the boundary next to it: read as
            # that, they ruled the index fixture's names off from its page
            # numbers, where the source has only a frame.
            for boundary in range(1, ncols):
                seps[boundary] = "@{}" if boundary in _leader_joins else ""
            # And the frame stands where it was printed from the text, not
            # a \tabcolsep off it: the index fixture's frame is 22pt out
            # from its names and 21pt from its page numbers.
            _scale = _A4_FULL_WIDTH_CM * _PT_PER_CM
            _fx0, _fx1 = _table_md.get("table_rule_x0"), _table_md.get("table_rule_x1")
            _pad_l = _pad_r = None
            if _fx0 is not None and seps[0] == "|" and col_min_x0 and _text_start(0) is not None:
                _pad_l = max(0.0, (_text_start(0) - _fx0) * _scale)
                seps[0] = f"|@{{\\hspace{{{_pad_l:.2f}pt}}}}"
            if _fx1 is not None and seps[ncols] == "|" and col_max_x1 and col_max_x1[-1] is not None:
                _pad_r = max(0.0, (_fx1 - col_max_x1[-1]) * _scale)
                seps[ncols] = f"@{{\\hspace{{{_pad_r:.2f}pt}}}}|"
            # The columns' bounds on the source page and in the tabular, so
            # a rule the source stops short of the frame is drawn so - the
            # index fixture's rule under its heading ends 20pt inside it.
            # Each column meets the next halfway across the gap between
            # them, a \tabcolsep either side.
            if _pad_l is not None and _pad_r is not None and col_width_cm is not None and all(
                _text_start(i) is not None for i in range(ncols)
            ):
                _sep_frac = _tabcolsep_pt / _scale
                _source_bounds = [_fx0] + [
                    _text_start(i) - (0.0 if i in _leader_joins else _sep_frac) for i in range(1, ncols)
                ] + [_fx1]
                _x = _rule_w_pt + _pad_l
                _emitted_bounds_pt = [_rule_w_pt / 2.0]
                for i in range(ncols):
                    _x += round(col_width_cm[i], 2) * _PT_PER_CM
                    if i < ncols - 1:
                        _join = i + 1 in _leader_joins
                        _emitted_bounds_pt.append(_x + (0.0 if _join else _tabcolsep_pt))
                        _x += 0.0 if _join else 2 * _tabcolsep_pt
                _emitted_bounds_pt.append(_x + _pad_r + _rule_w_pt / 2.0)
        col_spec = seps[0] + "".join(
            part + seps[i + 1] for i, part in enumerate(col_spec_parts)
        )
    else:
        # Every column gets a pipe on both sides here (the fallback grid),
        # so a header \multicolumn override needs the same on both sides
        # too, not just the span-cell convention's own unconditional "|".
        seps = ["|"] * (ncols + 1)
        col_spec = "|" + "|".join(col_spec_parts) + "|"

    def _place_at_printed_x(text: str, col: int, x0: float, x1: float, min_gap: float) -> str:
        """Set a cell's text where the source printed it, not flush with
        its column's values.

        A column is set flush right or left for its VALUES. Two kinds of
        cell do not follow them in print: a lone "•" standing in for a
        missing number, which the source centres under the figures
        (flushing it put every one of the decimal/binary fixture's dots
        5-8px right), and a heading, which that fixture sets over its
        column ("Binary" 16.4pt from its rule where the digits start at
        7.3pt; flushing it put both headings 8.5pt left). The same holds
        for a sub-column set inside another column: the voltage-regulator
        fixture's condition ranges (33pt in from "Tj = 25 C") and its
        "with line"/"with load" sub-labels (71pt in). Those are placed
        only past _PLACE_INDENT_PT, so ordinary values keep the column's
        calibrated indent. The gap between the text and the
        column's set edge is taken from their measured positions and
        held open with an invisible rule; an hspace would not do, since a
        trailing one on a raggedleft cell is trimmed away with the
        paragraph's last glue.
        """
        # Against the column's usual edge in the same boxes: where the
        # column's set edge itself lands is the indent's business (from the
        # ink), and a box compared with a box carries no OCR bias. A cell
        # printed past the usual edge - "uV/VOUT" overhanging the voltage-
        # regulator fixture's UNITS column - is given the overhang back with
        # a negative kern.
        if col_is_right is None or col >= len(col_is_right) or col >= len(col_edge_x0):
            return text
        scale = _A4_FULL_WIDTH_CM * _PT_PER_CM
        if col_is_right[col]:
            if col_edge_x1[col] is None:
                return text
            gap = (col_edge_x1[col] - x1) * scale
        else:
            if col_edge_x0[col] is None:
                return text
            gap = (x0 - col_edge_x0[col]) * scale
        if abs(gap) <= min_gap:
            return text
        # A p{} cell opens in vertical mode, where a leading \kern is a
        # vertical one: the cell's \vtop then took its height from the
        # kern and hung its text a line low - the index fixture's
        # "C. ITOH ELECTRONICS" 7.7pt under where its step put it.
        # \leavevmode starts the line first.
        if gap > 0:
            hold = f"\\rule{{{gap:.2f}pt}}{{0pt}}"
            return text + hold if col_is_right[col] else hold + text
        return text + f"\\kern{gap:.2f}pt " if col_is_right[col] else f"\\leavevmode\\kern{gap:.2f}pt " + text

    # One grid of dots for a leader that runs across a closed-up boundary
    # (_leader_joins). \dotfill centres its dots in each cell's own space,
    # so the two halves of one leader met out of step - 2pt of nothing at
    # the boundary on the index fixture. Aligned leaders set each dot a
    # whole pitch from its cell's left edge, and the second cell's dots are
    # set off by what the first column's width leaves over a whole number
    # of pitches, so they go on where the first cell's left off.
    _dot_pitch_pt = _DOT_PITCH_EM * (median_pt or 8.0)

    def _dots_at(phase_pt: float, overhang_pt: float = 0.0) -> str:
        """Aligned leader dots, phase_pt into each pitch; overhang_pt runs
        the leader on past its cell, so the dot whose pitch straddles a
        boundary is set (a leader sets only whole pitches)."""
        return (
            f"\\leaders\\hbox to {_dot_pitch_pt:.3f}pt{{\\kern{phase_pt:.3f}pt\\makebox[0pt]{{.}}\\hss}}"
            f"\\hfill\\kern{-overhang_pt:.3f}pt "
        )

    def _joined_leaders(text: str, col: int) -> str:
        if col_width_cm is None or "\\dotfill" not in text:
            return text
        half = _dot_pitch_pt / 2.0
        if col + 1 in _leader_joins:
            # Its dots on the next cell's grid coincide with the next
            # cell's own, so running on a pitch past the boundary only
            # sets the one the boundary cut.
            return text.replace("\\dotfill", _dots_at(half, _dot_pitch_pt))
        if col in _leader_joins and col - 1 < len(col_width_cm):
            left_over = (round(col_width_cm[col - 1], 2) * _PT_PER_CM) % _dot_pitch_pt
            return text.replace("\\dotfill ", _dots_at((half - left_over) % _dot_pitch_pt), 1)
        return text

    def _fit_to_column(text: str, col: int) -> str:
        """A one-line cell of a narrow column, boxed to the column's width
        and set against its set edge: a cell wider than the column runs
        into the padding on its ragged side, as the source printed it,
        instead of wrapping or widening the column for everyone."""
        if col_width_cm is None or is_wide[col] or not text:
            return text
        indent = _col_indent_pt[col] if col < len(_col_indent_pt) else 0.0
        width = col_width_cm[col] * _PT_PER_CM - (indent if indent > 0.05 else 0.0)
        side = "l" if col_is_right is not None and not col_is_right[col] else "r"
        return f"\\makebox[{width:.2f}pt][{side}]{{{text}}}"

    def _span_spec(col: int, col_span: int, spec: str) -> str:
        """A \\multicolumn's own column spec, with the rules it replaces.

        A column's left rule belongs to the column before it - only the
        first column owns one - so a \\multicolumn repeats a left rule
        only at column 0. Repeating it anywhere else draws it twice and
        widens the column by a rule's width: the voltage-regulator
        fixture's centred "CONDITIONS" heading pushed every rule right
        of it 1.3pt out that way.
        """
        left = seps[col] if col == 0 else ""
        right = seps[min(col + col_span, len(seps) - 1)]
        return f"{left}{spec}{right}"

    def _render_cell(cell: Any, col: int, row_idx: int = -1) -> str:
        if (
            row_idx == 0
            and col < len(header_is_centered)
            and header_is_centered[col]
            and not isinstance(cell, tuple)
        ):
            # This column's OWN data cells stay in col_spec_parts' left/
            # right setting (a binary code or a wrapped sentence, still
            # set the way the source set it) - only the group-heading text
            # in row 0 itself is centered, via a one-cell \multicolumn
            # that overrides just this cell's column type without
            # touching col_spec for every other row in the same column.
            if col_width_cm is not None:
                width = f"{col_width_cm[col]:.2f}cm"
                cspec = f">{{\\centering\\arraybackslash}}p{{{width}}}" if is_wide[col] else "c"
            else:
                cspec = "c"
            return f"\\multicolumn{{1}}{{{_span_spec(col, 1, cspec)}}}{{{cell}}}"
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
                # A label the source printed on one line stays on one line:
                # boxed to its column it wrapped wherever our face runs wider.
                if (row_idx, col) in one_line:
                    width = "*"
                elif col_width_cm is not None:
                    width = f"{col_width_cm[col]:.2f}cm"
                else:
                    width = f"{wide_width_cm:.2f}cm" if is_wide[col] else "*"
                if col_span > 1:
                    # Both row_span and col_span: \multicolumn{\multirow{...}{...}{...}}
                    return f"\\multicolumn{{{col_span}}}{{{_span_spec(col, col_span, spec)}}}{{\\multirow{{{row_span}}}{{{width}}}{{{text}}}}}"
                else:
                    return f"\\multirow{{{row_span}}}{{{width}}}{{{text}}}"
            else:
                if col_span > 1:
                    return f"\\multicolumn{{{col_span}}}{{{_span_spec(col, col_span, spec)}}}{{{text}}}"
                return text
        return cell  # Not a span tuple, render as-is

    # Which rows carry a rule is the source's decision too, and it is the
    # cells that hold it. An earlier version hardcoded "frame plus a rule
    # under the header, never between rows" on the claim that printed
    # tables of this kind are ruled that way - measuring the fixtures
    # disproved it: the decimal/binary page is ruled that way, but the
    # voltage-regulator page rules under every single row.
    # The source's own horizontal rules, measured by the analyzer
    # (table.metadata["rule_y"]). When they are known they decide where
    # a horizontal rule is drawn, instead of the cells' border flags: a
    # flag is judged with a reach that scales with the glyphs, and it
    # dropped the rule above the voltage-regulator fixture's header (5.3pt
    # off against a 5.09pt reach) while inventing one under its "with
    # line" row, where the source prints none.
    _rules_pt = sorted(y * _A4_HEIGHT_PT for y in (_table_md.get("rule_y") or []))
    _rule_extent = dict(zip(_rules_pt, _table_md.get("rule_x_extent") or []))
    # Each rule at the weight it was printed (TeX pt from PDF pt); the
    # table's median, \arrayrulewidth, where it was not measured.
    _rule_weight = {
        r: w * 72.27 / 72.0 for r, w in zip(_rules_pt, _table_md.get("rule_weight_pt") or []) if w > 0
    }

    def _weight_of(rule_pt: Optional[float]) -> float:
        return _rule_weight.get(rule_pt, _rule_w_pt) if rule_pt is not None else _rule_w_pt
    _row_centre_pt: List[Optional[float]] = []
    _row_top_pt: List[Optional[float]] = []
    for _grow in grid:
        _boxes = [
            c.visual_layout.bounding_box for c in _grow
            if getattr(c, "visual_layout", None) is not None and c.visual_layout.bounding_box is not None
        ]
        _row_centre_pt.append(
            sum((b.y0 + b.y1) / 2.0 for b in _boxes) / len(_boxes) * _A4_HEIGHT_PT if _boxes else None
        )
        _row_top_pt.append(min(b.y0 for b in _boxes) * _A4_HEIGHT_PT if _boxes else None)

    def _rule_below_pt(row: int) -> Optional[float]:
        """The measured rule between row and the next, or under the last."""
        lo = _row_centre_pt[row] if row < len(_row_centre_pt) else None
        if lo is None:
            return None
        hi = _row_centre_pt[row + 1] if row + 1 < len(_row_centre_pt) else None
        between = [r for r in _rules_pt if r > lo and (hi is None or r < hi)]
        return between[0] if between else None

    _top_rule_pt = (
        max((r for r in _rules_pt if r < _row_centre_pt[0]), default=None)
        if _rules_pt and _row_centre_pt and _row_centre_pt[0] is not None else None
    )

    def _to_tabular_pt(x: float) -> float:
        """A source x (page fraction) in the emitted tabular, column by
        column, so a column set wider or narrower than its source carries
        what lies inside it along."""
        c = max(0, min(ncols - 1, bisect.bisect_right(_source_bounds, x) - 1))
        lo, hi = _source_bounds[c], _source_bounds[c + 1]
        share = (x - lo) / (hi - lo) if hi > lo else 0.0
        e_lo, e_hi = _emitted_bounds_pt[c], _emitted_bounds_pt[c + 1]
        return e_lo + max(0.0, min(1.0, share)) * (e_hi - e_lo)

    def _rule_cmd(rule_pt: Optional[float]) -> str:
        """The rule measured at rule_pt, as long as the source drew it.

        Most rules cross the whole table and stay \\hline. A sub-row rule
        does not: the voltage-regulator fixture rules "14.5 V < VIN < 30 V"
        off from "16 V < VIN < 22 V" only from that sub-column on, and a
        full \\hline struck through the label and "Tj = 25 C" beside them.
        Such a rule is drawn as a bare \\vrule of the same weight in a
        zero-width box, which takes exactly the height \\hline does.
        """
        extent = _rule_extent.get(rule_pt) if rule_pt is not None else None
        weight = _weight_of(rule_pt)
        full = f"\\noalign{{\\hrule height {weight:.2f}pt}}" if rule_pt in _rule_weight else "\\hline"
        if extent is None or _emitted_bounds_pt is None:
            return full
        tol = _PARTIAL_RULE_TOL_PT / _A4_WIDTH_PT
        if extent[0] <= _source_bounds[0] + tol and extent[1] >= _source_bounds[-1] - tol:
            return full
        a, b = _to_tabular_pt(extent[0]), _to_tabular_pt(extent[1])
        return (
            f"\\noalign{{\\hbox to 0pt{{\\hskip {a:.2f}pt"
            f"\\vrule width {b - a:.2f}pt height {weight:.2f}pt depth 0pt\\hss}}}}"
        )

    _sub_rules = [
        (x, y0 * _A4_HEIGHT_PT, y1 * _A4_HEIGHT_PT) for x, y0, y1 in (_table_md.get("sub_rule") or [])
    ]

    def _sub_rules_from(rule_pt: Optional[float]) -> str:
        """The sub-column rules hanging from the rule at rule_pt.

        Each is a \\vrule of the table's rule weight in a zero-width box,
        as deep as the distance to the rule it ends on, taken straight back
        with a \\vskip: the rows under it keep the heights the rule solve
        gave them, and every rule it joins lands where it was measured, so
        the segment meets both ends."""
        if rule_pt is None or _emitted_bounds_pt is None:
            return ""
        out = ""
        for x, y0, y1 in _sub_rules:
            if abs(y0 - rule_pt) > 0.5:
                continue
            depth = y1 - y0 - _weight_of(rule_pt) / 2.0 - _weight_of(
                min(_rules_pt, key=lambda r: abs(r - y1))
            ) / 2.0
            left = _to_tabular_pt(x) - _rule_w_pt / 2.0
            out += (
                f"\\noalign{{\\hbox to 0pt{{\\hskip {left:.2f}pt\\vrule width {_rule_w_pt:.2f}pt "
                f"height 0pt depth {depth:.2f}pt\\hss}}\\vskip -{depth:.2f}pt}}"
            )
        return out

    def _row_ruled_below(index: int) -> bool:
        if _rules_pt:
            return _rule_below_pt(index) is not None
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
    _has_top_rule = (
        _top_rule_pt is not None if _rules_pt
        else bool(has_any_border and grid and _any_border(grid[0], "border_top"))
    )
    if _has_top_rule:
        body_lines.append(_rule_cmd(_top_rule_pt) if _rules_pt else "\\hline")

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
        # The outer envelope, deliberately, though it is measurably the
        # wrong idea on one fixture and the right one on the other.
        #
        # Wrong on the decimal/binary fixture: its two halves are
        # independent number sequences, so row 16 carries a stray
        # ellipsis mark 5pt below "15"/"00001111"'s baseline, and the
        # envelope reads that GAP as 1.34x the tightest row's height
        # when the row's own tallest cell is exactly one line. That row
        # then wins space it does not need (+4.9pt of step against the
        # source).
        #
        # Right on the voltage-regulator fixture: it splits a two-line
        # CONDITIONS entry into two separate TableCells inside ONE row,
        # and those really do stack, so their union IS that column's
        # height.
        #
        # Grouping by rendered column - union within a column, max
        # across columns - should satisfy both, and it does fix the
        # first: rows 15-18 all step +0.6pt afterwards instead of one
        # row jumping +4.9pt. It has now been measured twice anyway,
        # the second time after \tabcolsep and the per-column indents
        # were corrected (the confounders blamed the first time), and
        # both times the voltage-regulator fixture lost far more than
        # the other gained: fair 24.8% -> 27.2% and official 25.9% ->
        # 26.4%, against 16.1% -> 15.7% fair and 17.3% -> 17.6%
        # official on the decimal/binary one.
        #
        # Why, measured rather than assumed: the stacked CONDITIONS
        # cells DO share a bin (x0 0.5422 and 0.5959 both land in
        # column 1), so grouping keeps those stacks intact - rows 2 and
        # 6 come out identical either way. What grouping actually
        # changes are rows whose cells sit in DIFFERENT columns a
        # couple of thousandths apart in y: row 11 measures 1.37x under
        # the envelope and 1.00x grouped, row 4 1.13x. Collapsing them
        # is the more honest reading of those rows, and the fixture
        # still gets worse - because arraystretch is solved from the
        # TOTAL demanded height, so removing inflation those rows never
        # needed leaves the solve stretching everything else to fill
        # the same table (1.045 -> 1.099). The envelope's flaw and this
        # fixture's layout happen to cancel; the honest formula does
        # not. That makes this a problem with the global solve, not
        # with either height formula, and swapping formulas alone
        # cannot fix it.
        # One exception to the envelope, and only one: a bare placeholder
        # mark sitting on its OWN baseline. The stray ellipsis in row 16
        # is a cell of the table's OTHER number sequence that
        # _merge_stray_rows folds into this row on purpose - the
        # stop-listed roundtrip test asserts exactly that grid, and its
        # own header documents the +4.9pt offset - so the merge cannot be
        # undone here. But a mark that is not on the row's line is not
        # part of the row's HEIGHT either, and counting it is what earns
        # that row 5.83pt of extra space against a measured need of
        # 0.5pt.
        #
        # Scoped so it can only ever fire on that shape: the cell must be
        # one or two characters (a dot, a dash - never a word) AND sit
        # further from the row's own baseline than the same tolerance
        # _group_into_rows uses to decide what shares a line at all. The
        # marks in rows 3 and 18 share their row's y0 exactly and stay
        # counted; a row that is nothing BUT such marks (rows 19-20, a
        # lone ellipsis of the left-hand sequence) keeps its own height,
        # since there is no content baseline to measure it against. The
        # voltage-regulator fixture has no cell of this shape at all, so
        # it cannot be touched.
        boxes = []
        for cell in row:
            vl = getattr(cell, "visual_layout", None)
            cbb = getattr(vl, "bounding_box", None) if vl else None
            if cbb is not None:
                boxes.append((cbb, _cell_text(cell).strip()))
        if not boxes:
            return None
        _content_y0s = [b.y0 for b, text in boxes if len(text) > 2]
        if _content_y0s:
            _baseline_y0 = min(_content_y0s)
            boxes = [
                (b, text) for b, text in boxes
                if len(text) > 2 or abs(b.y0 - _baseline_y0) <= _ROW_BASELINE_TOLERANCE
            ]
        if not boxes:
            return None
        return max(b.y1 for b, _ in boxes) - min(b.y0 for b, _ in boxes)

    row_heights = [_row_height_fraction(row) for row in grid]
    _valid_rh = [h for h in row_heights if h is not None and h > 0]
    _baseline_rh = min(_valid_rh) if _valid_rh else None

    # Real per-row y0-to-y0 step to the NEXT row (not this row's own
    # content span) - used below, unthresholded (every row's own real
    # deviation from the table's tightest step, not just the ones over
    # some outlier cutoff), row 0 included (see the comment further down
    # for the real tradeoff that decision carries).
    def _row_min_y0(row: List[Any]) -> Optional[float]:
        y0s = [
            cbb.y0
            for cell in row
            for cbb in [getattr(getattr(cell, "visual_layout", None), "bounding_box", None)]
            if cbb is not None
        ]
        return min(y0s) if y0s else None

    _row_y0s = [_row_min_y0(row) for row in grid]
    row_gaps: List[Optional[float]] = [None] * len(grid)
    for i in range(len(grid) - 1):
        y0, y1 = _row_y0s[i], _row_y0s[i + 1]
        if y0 is not None and y1 is not None:
            row_gaps[i] = y1 - y0
    _valid_gaps = [g for g in row_gaps if g is not None and g > 0]
    _baseline_gap = min(_valid_gaps) if _valid_gaps else None

    # A second signal alongside row_heights: each row's own y0-to-y0 STEP
    # to the next row (not its own content span). On tables with a
    # wrapping column (voltage-regulator), this signal regressed the
    # overlay test every way it was tried (see the "fold-in" and
    # "unthresholded" write-ups below and further up this file for the
    # exact numbers) - that fixture's own row-to-row gaps flag several
    # outliers (one row measuring 3x the table's baseline step) that
    # compete for the SAME proportional extra-space budget row_heights'
    # own outliers already use, so a big new demand from this signal
    # starves rows row_heights was already correctly handling. Gated to
    # the no-wrapping branch only (below); row_heights alone is what the
    # wrapping fixture measures best against.

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
    # _CHAR_WIDTH_CM (0.17) was calibrated at an 8pt (footnotesize)
    # baseline - this table's own median_pt can be much smaller (5.48pt
    # on the voltage-regulator fixture), where real glyphs are
    # narrower and more of them fit per line than the unscaled constant
    # assumes. Same scaling already used for the tabcolsep content
    # floor, recomputed here rather than relying on that floor's local
    # variable, which only exists when real column rules were found.
    _wrap_char_width_cm = 0.17 * ((median_pt or 8.0) / 8.0)

    def _row_line_step(row_idx: int) -> float:
        """How far apart the lines of a row's tallest cell are set: its
        printed pitch where it is a stacked cell, the face's line else."""
        pitches = [v for (r, _), v in line_pitch.items() if r == row_idx and v > 0]
        return max(pitches) if pitches else _unstretched_line_pt

    def _row_line_count(row_idx: int) -> int:
        if col_width_cm is None or row_idx >= len(rendered_rows):
            return 1
        styled_cells, texts = rendered_rows[row_idx]
        best = 1
        for col, raw in enumerate(texts):
            if col < len(is_wide) and is_wide[col] and raw and col < len(col_width_cm):
                styled = styled_cells[col] if col < len(styled_cells) else ""
                if isinstance(styled, tuple):
                    if styled[1] > 1:
                        # A \multirow cell's text lies over the rows it
                        # spans and adds no height to this one.
                        continue
                    styled = styled[3]
                m = re.search(r"\\fontsize\{([0-9.]+)\}", styled or "")
                size = float(m.group(1)) if m else (median_pt or 8.0)
                segments = raw.split("\n") if (row_idx, col) in stacked else [raw.replace("\n", " ")]
                counts = [
                    _wrapped_line_count(
                        seg, col_width_cm[col] * _PT_PER_CM, size, "\\bfseries" in (styled or ""),
                    )
                    for seg in segments
                ]
                lines = None if any(n is None for n in counts) else sum(counts)
                if lines is None:
                    chars_per_line = max(1.0, col_width_cm[col] / max(_wrap_char_width_cm, 0.01))
                    lines = max(1, -(-len(raw) // int(chars_per_line)))
                best = max(best, lines)
        return best

    _total_lines = sum(_row_line_count(i) for i in range(len(rendered_rows))) if rendered_rows else 0
    _any_wrapping = _total_lines > len(rendered_rows)

    # For wrapping tables specifically: a row's row_heights ratio (its
    # own real source content span vs the table's tightest row) can
    # exceed what its own _row_line_count already accounts for - a
    # merged multi-line cell (_merge_orphan_rows) that happens to fit on
    # ONE rendered line once this table's column width and font size
    # allow it, but whose SOURCE printed the same content across several
    # real physical lines. Folding ONLY that excess into the SAME solve
    # _base_line_pt comes from (below) reserves real room for it, rather
    # than the after-the-fact budget/scale-down further down, which -
    # confirmed directly on the voltage-regulator fixture - starved a
    # real outlier to ~18% of its actual need: row 6's merged "Output
    # Voltage" condition cell (source: three separate condition lines,
    # this rendering: one line, since the column is wide enough and the
    # font small enough to fit all three) needed ~28pt of real extra
    # space, and the unaware solve's own budget only had ~5pt left for
    # it once its own "row count already ==row count, nothing wraps by
    # width" arraystretch had already spent the rest.
    # A row's envelope is capped at the STEP to the next row. row_heights
    # spans a row's cells from min y0 to max y1, which reaches onto the
    # next printed line whenever a cell's continuation sits there - and
    # when that continuation survived as its own grid row, we render it as
    # a row AND reserve its height here, paying for the same printed line
    # twice. The voltage-regulator fixture does exactly that: rows 2 and 4
    # measure 1.80 and 1.91 baselines and take +5.28pt and +5.99pt of
    # extra, while their continuations are already emitted as rows 3 and 5
    # with steps of their own.
    #
    # The cap leaves the case this reservation exists for untouched: row 6
    # folded three printed lines INTO one cell via _merge_orphan_rows, so
    # no separate row carries them and the step to the next row (24.6pt)
    # is larger than the envelope, not smaller.
    _wrap_row_extra_units = [0.0] * len(row_heights)
    if _any_wrapping and _baseline_rh:
        for i, rh in enumerate(row_heights):
            if rh:
                gap = row_gaps[i] if i < len(row_gaps) else None
                # Zeroing the extra outright when the envelope overruns the
                # step - instead of capping it here - was tried and lost.
                # It does what it claims (the voltage-regulator fixture's
                # rows 2 and 4 went 0.714 and 0.661 units to 0.000, row 6's
                # merged cell kept its 2.161, fixture A never enters this
                # block at all) and its drift improved, +27.1pt -> +17.8pt,
                # with the official overlay 25.7% -> 23.6%. But it takes out
                # 8.8pt the source really has: that table measured 182.0pt
                # rule-to-rule against the source's 190.8 (+0.5pt before),
                # its fair overlay went 23.8% -> 26.6% and its matching
                # horizontals 3/15 -> 2/15. The official metric improved
                # only because its crop pads the top and hides a table that
                # is now too SHORT; the fair crop, which normalizes on the
                # text extent, sees it. Capping keeps the overhang out
                # without spending height the source spent.
                if gap and gap > 0:
                    rh = min(rh, gap)
                ratio = rh / _baseline_rh
                if ratio > 1.15:
                    own_lines = _row_line_count(i) if i < len(rendered_rows) else 1
                    _wrap_row_extra_units[i] = max(0.0, ratio - own_lines)
    _wrap_extra_units_total = sum(_wrap_row_extra_units)

    # A row's SHARE of the extra-space budget (see raw_extra_pt below) is
    # a ratio, independent of how tall a single baseline line actually
    # ends up. When NOTHING in this table wraps (_total_lines exactly
    # equals the row count), fold that ratio into the SAME solve that
    # sizes dynamic_arraystretch, so the baseline it picks already leaves
    # room for it - solving arraystretch from total_lines alone and only
    # THEN handing out extra space (the general case below) leaves no
    # room for it in this specific case: with every row exactly 1 line,
    # a naive len(rendered_rows)*_base_line_pt is mathematically EQUAL to
    # target_height_pt by construction, a zero budget for every table
    # without a wrapping column no matter how tall one of its rows
    # actually measures. Confirmed directly on the decimal/binary
    # fixture (no wide columns at all): row 16 ("00001111") measures 34%
    # taller than the table's own shortest row, but extra_scale still
    # came out exactly 0.0 under the general-case formula, so every row
    # rendered at the identical uniform height.
    #
    # Once a table has even one wrapping row, this same fold-in makes
    # things WORSE, not better: a wrapped cell's source bbox is already
    # taller than the baseline BECAUSE it wraps, so _total_lines already
    # reserves height for it, and folding its own row_heights ratio in
    # too double-budgets that one row. Confirmed directly on the
    # voltage-regulator fixture (which does have wrapping columns): the
    # fold-in regressed its overlay mismatch twice, once unconditionally
    # (24.2% -> 25.4%) and once even after skipping wrapped rows'  own
    # ratio (24.2% -> 27.0%, since OTHER single-line outlier rows in
    # that same table then got the full unscaled ratio the old
    # proportional scale-down used to temper). The general-case formula
    # below is what that fixture already measures best against, so a
    # table with any wrapping keeps using it unchanged.
    # The gate below keeps the gap signal away from wrapping tables. It
    # has been opened and measured, and the starvation it causes is real:
    # reading the per-row \tabularnewline[Xpt] out of the
    # voltage-regulator fixture's own tex, 6 rows of 19 got any extra at
    # all, eight rows needing ~4.4-4.9pt each got 0.00, and the one row
    # genuinely needing 20.5pt got 14.85 - which is why that table
    # renders 27pt shorter than its source. Opening the gate fixed
    # exactly that (those rows went to 5.6-6.3pt, row 6 to 26.31).
    #
    # It still measured worse, twice, and the second attempt is the
    # informative one. The first overshot by ~30% (119.7pt granted
    # against 92.3pt of real need) because a gap ratio is in units of
    # the tightest GAP while its multiplier is a base LINE - 4.1pt
    # against 6.58pt on that fixture. Converting the signal into
    # unstretched-line units brought it to 76.7pt granted, only two
    # rows out by more than 1.5pt across both fixtures, and the table's
    # height from 27pt short to 14.8pt short. Both fixtures still lost:
    # fair 24.8% -> 26.5% and official 25.9% -> 26.6% on this one,
    # 16.1% -> 16.2% and 17.3% -> 17.6% on the other, with its row
    # drift going -1.8pt -> +16.1pt.
    #
    # The tell in both runs: arraystretch pinned against its 0.8 floor.
    # The solve wants to shrink further and cannot, so the extra space
    # these rows correctly ask for has nowhere to come from and every
    # row is squeezed instead. That is the same wall the last two
    # attempts hit - one global stretch factor, a hard clamp, and a
    # target height that is short by construction (see target_height_pt
    # below). Reopening this gate without fixing that first will fail
    # the same way a fourth time.
    _extra_ratio = [0.0] * len(row_heights)
    if not _any_wrapping:
        if _baseline_rh:
            for i, rh in enumerate(row_heights):
                if rh:
                    ratio = rh / _baseline_rh
                    if ratio > 1.15:
                        _extra_ratio[i] = ratio - 1.0
        # Unthresholded this time: EVERY row's own real gap to the next
        # row, relative to the table's tightest gap - not just the ones
        # crossing some outlier cutoff. A table with no wrapping columns
        # at all can still have its data rows' own steps vary by a few
        # percent from each other (confirmed on the decimal/binary
        # fixture: 0.0170-0.0181, a real ~6% spread, not noise - every
        # value repeats across multiple row pairs, it is not one-off
        # jitter), and while any single row's share of that is tiny, 21
        # of them compounding in the SAME direction is exactly the kind
        # of one-row-at-a-time accumulating drift the visual overlay
        # keeps showing growing down the table.
        #
        # row 0's own transition (header-to-row-1) is included here on
        # purpose, after measuring both sides of that decision. Excluding
        # it (an earlier version of this comment) was chosen because
        # reproducing that one row's real, 52%-bigger-than-typical gap
        # measured WORSE against the stop-listed visual-overlay test
        # (15.4% -> 15.8%) - _output_table_rect, that test's own crop
        # heuristic, already pads the top of the ASSEMBLED crop by one
        # row's height (nothing on the source side gets the same
        # padding), and adding this row's own real extra gap on top of
        # that unrelated, test-side padding doubled up in the same
        # direction there. But measured against the SAME comparison with
        # that one-sided padding removed from both crops (a fair,
        # same-method-both-sides crop, built to check whether the padding
        # itself was hiding a real remaining defect - see the "fair
        # crop" debug tooling), including row 0 is a clear net
        # improvement (16.5% -> 15.2%) - the constant gap the earlier,
        # excluded version left behind is real, source-side geometry, not
        # an artifact of anyone's crop math. Kept here at the cost of a
        # small, known, accepted regression on the stop-listed test's own
        # number (15.4% -> 15.6%) because the fair comparison is the
        # truer measure of whether the rendered table actually matches
        # the source, and that test's padding asymmetry - not this row -
        # is what was distorting the 15.4% in the first place.
        if _baseline_gap:
            for i in range(len(row_gaps)):
                g = row_gaps[i]
                if g:
                    ratio = g / _baseline_gap
                    if ratio > 1.0:
                        _extra_ratio[i] = max(_extra_ratio[i], ratio - 1.0)
    _extra_ratio_total = sum(_extra_ratio)

    if bb is not None and rendered_rows:
        # bb is the union of the CELLS' boxes, so it stops at the
        # outermost glyph and misses both the rules the source drew and
        # the air it left above the first row and below the last. The
        # real spans are larger - measured rule-to-rule, the
        # decimal/binary fixture is 364.9pt against a bbox of 350.4, and
        # the voltage-regulator one 190.8pt against 172.1 - and
        # table_rule_y0/y1 now carry them (the analyzer records them the
        # same way it records the vertical rules).
        #
        # They are deliberately NOT used here. Substituting the real
        # height made every measurement worse: the decimal/binary
        # fixture's own rendered height went from 364.8pt - already
        # within 0.1pt of its source - to 379.5pt, its per-row step from
        # +0.4pt to +1.0pt against the source's, and its overlay from
        # 17.3% to 17.4% official, with the voltage-regulator fixture
        # going 25.9% -> 26.3%. The reason is that this value is not
        # "how tall the table should be", it is one input to a formula
        # whose output lands about 14.5pt ABOVE it: the solve counts
        # rows and leading, while the compiled table also carries its
        # \hline rules, the per-row \tabularnewline extras and the
        # cells' own padding, none of which the formula models. The
        # bbox figure is short by almost exactly that amount, so it is
        # the input that makes the OUTPUT come out right. Feeding the
        # true height in just adds the unmodelled 14.5pt on top again.
        # Fixing this properly means modelling what the formula is
        # missing, not swapping its input.
        target_height_pt = (bb.y1 - bb.y0) * _A4_FULL_HEIGHT_CM * _PT_PER_CM
        # The row_gaps-driven _extra_ratio (above) sums one term per
        # GAP (len(rendered_rows)-1 of them - there is no "trailing
        # gap" after the last row), but _total_lines counts one unit
        # per ROW (len(rendered_rows) of them) - a genuine, if subtle,
        # unit mismatch: only when _extra_ratio_total is actually
        # nonzero (the no-wrapping branch with real row-gap data) does
        # the -1 correction apply, keeping wrapping tables (whose
        # _extra_ratio_total is always 0) on the untouched formula.
        # A fourth attempt rebuilt this whole solve and lost; two facts
        # from it are worth keeping, because both look like fixes and
        # only one of them is even half true.
        #
        # The 0.8 floor really does bind. Every row's deviation was
        # re-expressed in absolute points (straight from the source's
        # own gaps, so nothing got rescaled by the solve's own answer),
        # subtracted from the budget, and emitted as measured. The
        # voltage-regulator fixture's starvation went away - 95.9pt
        # granted against 92.3pt of measured need, where eight of its
        # rows had been getting 0.00 - and with the floor lowered to
        # 0.5 its stretch immediately took 0.61, exactly the value it
        # had been computing and unable to say. Its height went from
        # 27pt short of the source to 3.8pt short.
        #
        # And it still measured worse (fair 24.8% -> 27.0%, official
        # 25.9% -> 26.6%), because subtracting the extras from the
        # budget double-counts them: \tabularnewline[Xpt] ADDS to the
        # row height LaTeX already lays out, it does not replace it. The
        # arithmetic is unambiguous - that fixture's solve hit its
        # 172.1pt target exactly (76pt of base plus 95.9pt of extras)
        # while the compiled table came out 213pt, every row ~1.5pt
        # too tall, 19 times over. Reserving room for extras and then
        # also paying them is the same 14.5pt-unmodelled problem the
        # target_height_pt note above describes, scaled up.
        #
        # So: the floor is a real constraint, but lifting it only helps
        # once the extras stop being counted twice. A fifth attempt
        # starts there, not at the clamp.
        _line_count_units = _total_lines - 1 if _extra_ratio_total > 0 else _total_lines
        unstretched_pt = (
            _line_count_units + _extra_ratio_total + _wrap_extra_units_total
        ) * (median_pt or 8.0) * 1.2
        if unstretched_pt > 0:
            dynamic_arraystretch = max(0.8, min(1.5, target_height_pt / unstretched_pt))

    # The base row is the source's TIGHTEST row, taken directly. Solving
    # it from a total height instead (above) has to guess at everything
    # the formula does not model - the rules, the per-row extras, the
    # cells' own padding - and every attempt to feed it a better total
    # failed on that gap. A row's step is a measured quantity; there is
    # no reason to derive it from a sum.
    # The MEDIAN step, not the smallest. A table whose rows are split
    # into sub-rows (the voltage-regulator fixture stacks a two-line
    # condition inside one row) has steps of 4.1pt between those halves
    # against a median of 8.6pt - taking the minimum makes the base row
    # half of a real one, and every row then needs a surplus to climb
    # back, which overshoots. The median is the step an ordinary row
    # actually has. On a table without sub-rows the two agree anyway
    # (14.3 against 14.8pt on the decimal/binary fixture).
    _real_gaps_pt = sorted(
        g * _A4_FULL_HEIGHT_CM * _PT_PER_CM for g in row_gaps if g and g > 0
    )
    _baseline_gap_pt = (
        _real_gaps_pt[len(_real_gaps_pt) // 2] if _real_gaps_pt else 0.0
    )
    # The 1.2 here is LaTeX's default leading, and deriving it from the
    # table's own smallest printed step instead was tried and lost. Two
    # things came out of it, both worth keeping written down.
    #
    # First, the per-cell \fontsize leading is INERT for row height in
    # these tables. Emitting one flat leading for every cell (wrong:
    # \fontsize{6.98}{4.37} sets 6.98pt type in a 4.37pt box) and then
    # emitting it proportionally per cell (\fontsize{6.98}{5.56},
    # \fontsize{3.12}{2.49}) produced byte-identical geometry on both
    # fixtures - height, drift, both overlays, every border count. Row
    # height comes from \arraystretch and the row's strut; a p{} cell's
    # baselineskip only shows up on text that WRAPS inside the cell, and
    # almost nothing in these tables does.
    #
    # Second, what actually moved was this line feeding the solve: a
    # smaller _unstretched_line_pt deepens _compress_floor_pt (-2.15pt ->
    # -4.35pt on the voltage-regulator fixture), which is the very change
    # disproved just below. Same mechanism, longer route, same verdict:
    #
    #   fixture B  drift +27.1pt -> +17.6pt, official 25.7% -> 24.6%,
    #              horizontals anchored 3/15 -> 6/15,
    #              but rule-to-rule +0.5pt -> -9.5pt and fair 23.8% -> 23.9%
    #   fixture A  rule-to-rule +0.1pt -> -0.5pt, drift -0.7pt -> -1.3pt
    #
    # The horizontals improve because the table is 9.5pt SHORT, not
    # because its rows landed where the source put them. Reverted.
    _unstretched_line_pt = (median_pt or 8.0) * 1.2
    if _baseline_gap_pt > 0 and _unstretched_line_pt > 0:
        dynamic_arraystretch = max(0.5, min(2.0, _baseline_gap_pt / _unstretched_line_pt))
    _base_line_pt = _unstretched_line_pt * dynamic_arraystretch

    # How far a row's first line stands above the row's strut. The strut
    # is the table's, set for its usual size; a cell in larger type is as
    # tall as its own capitals and ascenders, and the row with it. The
    # index fixture's 20.5pt heading rows each stood 5pt above theirs,
    # which pushed its entries 10pt down from the heading.
    _FONTSIZE_RE = re.compile(r"\\fontsize\{([\d.]+)\}")

    def _row_cap_pt(row_idx: int) -> Optional[float]:
        """How tall the capitals of a row's largest type stand."""
        if row_idx >= len(rendered_rows):
            return None
        sizes = [
            float(m) for styled in rendered_rows[row_idx][0]
            if isinstance(styled, str) for m in _FONTSIZE_RE.findall(styled)
        ]
        return _ASCENT * max(sizes) if sizes else None

    def _row_rise_pt(row_idx: int) -> float:
        cap = _row_cap_pt(row_idx)
        return max(0.0, cap - _STRUT_HEIGHT * _base_line_pt) if cap is not None else 0.0

    def _cap_step_pt(row_idx: int) -> float:
        """What a row's step to the next leaves out beyond the usual, set
        capital top to capital top as the source's boxes measure it: the
        next row's rise above its strut, less how much taller the next
        row's capitals are than this row's. Under a heading that rises to
        its own capitals an entry's capitals sit under the strut's
        headroom, and the index fixture's first entry came out 3pt low."""
        here, below = _row_cap_pt(row_idx), _row_cap_pt(row_idx + 1)
        if here is None or below is None:
            return 0.0
        return _row_rise_pt(row_idx + 1) - (below - here)

    # Each row gets exactly what the source leaves beyond the tightest
    # row: step_i = base + (gap_i - tightest) = gap_i. Nothing is
    # budgeted and nothing is scaled, so the extras cannot be paid twice
    # - the failure mode of every earlier version, which reserved room
    # for them in the stretch AND then emitted them on top.
    #
    # A wrapping row whose own content needs more than its gap implies
    # keeps that need: a merged multi-line cell is taller than the step
    # to the next row when the source printed the two close together.
    # A row whose source step is SHORTER than the baseline gets a
    # negative extra, not zero. \arraystretch hands every row the same
    # _base_line_pt and max(0.0, ...) could only ever add to it, so a
    # stacked continuation line - the voltage-regulator fixture steps
    # 4.1pt between the two halves of a condition against its 8.7pt
    # baseline - paid a full row and pushed everything below it down:
    # +34.9pt of cumulative drift, only 2 of 15 horizontals landing on
    # the source's.
    #
    # The floor is exactly what the stretch itself added. A row may give
    # back the space \arraystretch put above its natural line box; take
    # more than that and the rows overlap.
    # Deepening this floor to the row's OWN ink - row_heights[i] instead
    # of the table's line box, which would let a row shrink until it is
    # only as tall as what it holds - was tried and lost. The motive was
    # real: the voltage-regulator fixture's continuation rows step
    # 4.1-4.9pt where one natural line box is 6.58pt, so each sits ~4pt
    # too tall and the constant floor (-2.15pt there) cannot reach, while
    # that source itself runs tighter than its own ink (4.6pt steps under
    # ~5pt glyphs). It bought B's drift +27.1pt -> +24.4pt and its
    # official overlay 25.7% -> 24.5%, and cost geometry on BOTH fixtures:
    #
    #   fixture B  rule-to-rule +0.5pt -> -2.2pt, fair 23.8% -> 24.1%,
    #              horizontals 3/15 unchanged
    #   fixture A  rule-to-rule +0.1pt -> -0.6pt, drift -0.7pt -> -1.4pt,
    #              pixels moved 0.1pp, inside noise
    #
    # A is the fixture whose height was already exact, and this floor is
    # not gated on wrapping, so it reached A too. Same shape as the
    # zeroing attempt above - the padded official metric improves while
    # the geometry and the fair crop degrade - and the same answer: the
    # geometry decides. Reverted to the constant.
    _compress_floor_pt = min(0.0, _unstretched_line_pt - _base_line_pt)

    def _printed_span(cell: Any) -> Optional[Tuple[float, float]]:
        printed = (getattr(cell, "metadata", None) or {}).get("printed_x")
        if printed:
            return printed[0], printed[1]
        x0, x1 = _cell_x0(cell), _cell_x1(cell)
        return (x0, x1) if x0 is not None and x1 is not None else None

    def _disjoint_below(row: int) -> bool:
        """True when no cell of this row sits over any cell of the next.

        Two rows whose text shares no horizontal extent cannot print on
        top of each other however close they step - so such a row may be
        set as tightly as its source printed it, instead of being held at
        a full line box. The voltage-regulator fixture interleaves exactly
        so: "with line", "Quiescent Current Change" and "with load" step
        4.1 and 4.3pt apart, the label in the column's left part and the
        sub-labels indented past it.
        """
        if row + 1 >= len(grid):
            return False
        here = [sp for sp in (_printed_span(c) for c in grid[row]) if sp]
        there = [sp for sp in (_printed_span(c) for c in grid[row + 1]) if sp]
        if not here or not there:
            return False
        return all(a1 <= b0 or b1 <= a0 for a0, a1 in here for b0, b1 in there)
    raw_extra_pt = []
    for i in range(len(rendered_rows)):
        gap = row_gaps[i] if i < len(row_gaps) else None
        # The step to the next row holds this row's own lines too, which
        # its height already counts (_row_h_pt below): the extra is what
        # the step leaves beyond them. Counted in both, the pin description
        # fixture's stacked status lines reserved them twice - 116pt and
        # 74pt of blank under two rows, and the table no longer fit a page.
        surplus = (
            (gap * _A4_FULL_HEIGHT_CM * _PT_PER_CM) - _baseline_gap_pt
            - max(0, _row_line_count(i) - 1) * _row_line_step(i)
            - _cap_step_pt(i)
            if gap and _baseline_gap_pt > 0 else 0.0
        )
        content = (
            _wrap_row_extra_units[i] * _unstretched_line_pt
            if i < len(_wrap_row_extra_units) else 0.0
        )
        # A wrapping row still keeps its own need: its lines have to fit
        # whatever the step to the next row implies.
        floor = content if content > 0 else (
            -(_base_line_pt - 0.5) if _disjoint_below(i) else _compress_floor_pt
        )
        raw_extra_pt.append(max(floor, surplus))
    _extra_scale = 1.0

    # The air the source left between its outer rules and its outermost
    # glyphs. bb stops at the ink, so without this the top rule sits
    # straight on the first row's caps and the whole grid rides high
    # against the source: measured on the decimal/binary fixture the
    # source leaves 4.5pt above its first glyph where we left -0.5pt,
    # and that 5pt is the vertical offset the border mask shows.
    # Appended here rather than beside the \hline itself because the
    # page-height constant is only bound further down.
    _page_h_pt = _A4_FULL_HEIGHT_CM * _PT_PER_CM
    # These come from bb, an OCR box that on a scan sits INSIDE the ink
    # it covers, and measuring them from the ink instead was tried and
    # lost - not because the measurement is wrong, but because the error
    # is load-bearing.
    #
    # The measurement was verified two ways on the decimal/binary
    # fixture, by a rule-detection pass at 3x zoom and an independent
    # band probe at 4x: its top air is 1.4pt against the 3.3pt bb gives,
    # and its bottom air 0.8pt against bb's 11.0pt. Feeding those in put
    # the header separator at 24.0pt under the top rule where bb put it
    # at 26.0 and the source prints 21.9, and the border mask's worst
    # horizontal went 23px -> 13px with its median 11px -> 6px.
    #
    # And the table came out 12.1pt SHORT (rule-to-rule +0.1pt ->
    # -12.1pt, fair 15.8% -> 16.1%).
    #
    # The reason is that the ink measurement was itself wrong at the
    # bottom, on BOTH sides: a rule's anti-aliased fringe covers 30-40%
    # of the band, survives a "drop rows covering over half the width"
    # filter, and reads as ink hard against the rule. Measured instead
    # on the text layer, which has no fringe, this bb-derived air is
    # very nearly right:
    #
    #   source   top rule -> first line 3.7pt, last line -> rule 25.4pt
    #   rebuild  top rule -> first line 2.8pt, last line -> rule 26.8pt
    #
    # and the two tables' text spans agree to 0.2pt (335.7 against
    # 335.5). So this fixture's rows are NOT short; its outer geometry
    # is right to within 1.4pt, and the one real defect left in it is
    # the internal separator under the header, 4.1pt low. Do not
    # "correct" these airs from pixels again without checking the text
    # layer first.
    #
    # The voltage-regulator fixture was untouched throughout (23.8% fair,
    # 25.7% official, 3/15 horizontals, +0.2pt). Its own defect is a
    # different one and this measurement names it: the source prints 28
    # text lines inside 167.0pt where we print 21 inside 193.1pt.
    _rule_y0 = _table_md.get("table_rule_y0")
    _rule_y1 = _table_md.get("table_rule_y1")
    _top_air_pt = (
        max(0.0, (bb.y0 - _rule_y0) * _page_h_pt)
        if bb is not None and _rule_y0 is not None else 0.0
    )
    _bottom_air_pt = (
        max(0.0, (_rule_y1 - bb.y1) * _page_h_pt)
        if bb is not None and _rule_y1 is not None else 0.0
    )
    # This air is ADDED, and taking it back out of the first row's own
    # height so the rules below stay put was tried and lost. It does move
    # the rule: the decimal/binary fixture's source sets its header
    # separator 21.9pt under its top rule and we set ours at 26.0pt, and
    # compensating brought that to 22.7pt - the border mask's worst
    # horizontal went 23px -> 7px and its median 11px -> 3px, the closest
    # that fixture's borders have come.
    #
    # It pays for it out of the one text gap underneath. The step from
    # the header to the first data row went 22.7pt -> 19.3pt against a
    # source of 22.4pt: exact before, 3.0pt short after, and no other row
    # moved at all. Its fair overlay went 15.8% -> 16.2%, its official
    # 17.8% -> 18.0% and its cumulative drift -0.7pt -> -4.0pt, all of it
    # that single gap. One rule closer against one text step and two
    # honest measures worse is not a trade worth making.
    #
    # Worth remembering if it is tried again: the compensation must be
    # gated on _has_top_rule exactly as this vskip is. Gating only on
    # _top_air_pt > 0.1 subtracts air from a table that was never given
    # any - the voltage-regulator fixture computes the air (it has a
    # table_rule_y0) but emits no vskip (its border_top flags are all
    # False), and its fair overlay went 23.8% -> 25.9% and its matching
    # horizontals 3/15 -> 1/15 on that alone.
    # With the rules measured, the air under each one is the source's own
    # gap from that rule to the top of the row below it, less the gap
    # LaTeX already leaves between a row's top and its glyphs (the strut
    # sits 0.7 of the row high; cap and figure height is ~0.68 of the
    # size). One figure for the whole table was wrong on the voltage-
    # regulator fixture, whose rows sit 5.3, 3.2, 1.7pt... under their
    # rules.
    _natural_pad_pt = 0.7 * _base_line_pt - 0.68 * (median_pt or 8.0)

    # Where the source printed the text under each rule, read off its ink
    # by the analyzer: (top, bottom) below the rule's lower edge. Where it
    # is known the row's glyphs are centred where the source's are - the
    # boxes the fallback below reads come from the text layer, and on the
    # voltage-regulator fixture they put every row's text 1.5pt below the
    # print, 1.2pt at its centre. A band's first line is centred its cap
    # height below the band's top; the source's cap height is the median
    # height of its one-line bands (its glyphs are taller than ours, and a
    # band's own foot moves with its descenders and subscripts).
    _line_box_pt = line_box * _A4_HEIGHT_PT
    _text_band = {
        r: band for r, band in zip(_rules_pt, _table_md.get("text_band_pt") or [])
        if band is not None
    }
    _heights = sorted(
        b[1] - b[0] for b in _text_band.values() if b[1] - b[0] <= 1.5 * _line_box_pt
    )
    # With no one-line band to measure - the index fixture has one band,
    # its whole body under the rule beneath its heading - our own cap
    # height stands in. Zero there set the first entry half a capital
    # (2.8pt) too close under that rule.
    _source_cap_pt = _heights[len(_heights) // 2] if _heights else 0.68 * (median_pt or 8.0)
    # Our glyphs' centre under a row's top: the baseline sits on the
    # strut, 0.7 of the row down, and caps and figures reach 0.68 of the
    # size above it.
    _glyph_centre_pt = 0.7 * _base_line_pt - 0.34 * (median_pt or 8.0)
    _airs = sorted(
        b[0] + _source_cap_pt / 2.0 - _glyph_centre_pt for r, b in _text_band.items()
        if r != _top_rule_pt
    )
    _usual_air_pt = _airs[len(_airs) // 2] if _airs else None

    def _air_under_rule_pt(rule_pt: Optional[float], row: int) -> float:
        """Space to put between a rule and the row under it; negative lifts
        the row's text towards the rule."""
        band = _text_band.get(rule_pt) if rule_pt is not None else None
        if band is not None:
            return band[0] + _source_cap_pt / 2.0 - _glyph_centre_pt
        # Where the source's text under a rule could not be read - it runs
        # into the rule's fringe, as "with line" does on the voltage-
        # regulator fixture - it sits as the table's other rows do. Its box
        # would say otherwise: the text layer puts boxes above the print.
        if rule_pt is not None and _usual_air_pt is not None and rule_pt in _rules_pt:
            return _usual_air_pt
        top = _row_top_pt[row] if 0 <= row < len(_row_top_pt) else None
        if rule_pt is None or top is None:
            return 0.0
        return max(0.0, (top - rule_pt) - _natural_pad_pt)

    _ruled_sides = "|" in col_spec

    def _air_cmd(air_pt: float) -> str:
        """Space under a rule. A \\noalign skip stops every vertical rule
        for its height - the index fixture's frame had a 16pt gap down both
        sides under its heading's rule - so where the table has verticals,
        space is an empty row, which draws them: its own line high, its
        \\tabularnewline making up the rest either way."""
        if air_pt <= 0 or not _ruled_sides:
            return f"\\noalign{{\\vskip {air_pt:.2f}pt}}"
        return " & " * (ncols - 1) + f" \\tabularnewline[{air_pt - _base_line_pt:.2f}pt]"

    if _rules_pt and _top_rule_pt is not None:
        _top_air_pt = _air_under_rule_pt(_top_rule_pt, 0)
    if _has_top_rule and abs(_top_air_pt) > 0.1:
        body_lines.append(_air_cmd(_top_air_pt))

    # Rule-driven row heights. For a ruled table the source's own rules are
    # the ground truth for where each row ends: a row's text steps are not
    # the distance between its rules once sub-rows or wrapped cells sit
    # inside one ruled band, and deriving heights from text left the
    # voltage-regulator fixture with 3 of its 15 horizontals on target and
    # +27pt of drift, while every one of those rules had been detected to
    # within 0.1pt.
    #
    # What this loop emits is fully known - a row is _base_line_pt tall
    # plus one unstretched line per extra wrapped line, plus its
    # \tabularnewline extra; a rule adds \arrayrulewidth (0.4pt); a vskip
    # adds itself - so each drawn rule's position is tracked as it is
    # emitted, and the extra of a row with a measured rule under it is
    # solved to put that rule where the source has it, measured from the
    # first drawn rule. Every target is taken from that anchor, not from
    # the previous row, so a row clamped at its floor does not carry its
    # error down the table.
    _ARRAYRULE_PT = _weight_of(_top_rule_pt) if _rules_pt else _rule_w_pt
    _y_pt = 0.0            # emitted position of the current point
    _anchor = None         # (emitted centre, measured position) of the first drawn rule
    _pre_air_pt = 0.0      # vskip emitted under the rule just drawn
    if _has_top_rule:
        if _top_rule_pt is not None:
            _anchor = (_ARRAYRULE_PT / 2.0, _top_rule_pt)
        _y_pt = _ARRAYRULE_PT
        _pre_air_pt = _top_air_pt if abs(_top_air_pt) > 0.1 else 0.0

    for i, (cells, _) in enumerate(rendered_rows):
        if has_any_border:
            rule = (
                _rule_cmd(_rule_below_pt(i) if _rules_pt else None)
                if i < len(grid) and _row_ruled_below(i) else ""
            )
        else:
            rule = "\\hline" if i in (0, len(rendered_rows) - 1) else ""
        # A position another cell spans is not a cell of its own. One
        # spanned across from the left is consumed by that \multicolumn;
        # one spanned down from a row above still takes its column here,
        # empty, or every cell after it moves one column left - the
        # voltage-regulator fixture's last row put "+25 C < Tj < +150 C"
        # under CHARACTERISTICS and "0.3" under TYP that way.
        rendered = []
        for col, c in enumerate(cells):
            origin = span_map.get((i, col))
            if origin is not None and origin[0] != i:
                rendered.append("")
            elif origin is None:
                if (
                    isinstance(c, str) and (i, col) in printed_x
                    and not (i == 0 and col < len(header_is_centered) and header_is_centered[col])
                ):
                    c = _place_at_printed_x(c, col, *printed_x[(i, col)])
                if isinstance(c, str) and (i, col) in one_line and not (
                    i == 0 and col < len(header_is_centered) and header_is_centered[col]
                ):
                    c = _fit_to_column(c, col)
                if isinstance(c, str):
                    c = _joined_leaders(c, col)
                rendered.append(_render_cell(c, col, row_idx=i))
        extra = ""
        _row_extra_pt = raw_extra_pt[i] * _extra_scale if i < len(raw_extra_pt) else 0.0
        if i == len(rendered_rows) - 1:
            _row_extra_pt += _bottom_air_pt
        # A rule under a row splits that row's extra space, it does not
        # sit under all of it. Measured on the decimal/binary fixture:
        # the source puts its header separator 18.2pt below the header
        # text and the next row's text 22.4pt below, so 4.2pt of that
        # step falls UNDER the rule. Emitting the whole extra before the
        # \hline put our rule 23.2pt below the header text with the next
        # row's text 22.7pt below it - the rule landing on the text
        # instead of above it, and the separator 4.1pt lower than the
        # source's.
        #
        # The amount is the same measured rule-to-text clearance the top
        # of the table already uses, and it is TAKEN FROM the row's own
        # extra rather than added, so the table's height does not move.
        _rule_air_pt = 0.0
        # What this buys and costs, measured by switching it off with
        # everything else held still: fixture A's header separator sits
        # at 22.8pt under the top rule with it and 26.0pt without (the
        # source prints 21.9pt), its horizontals 2/2 against 1/2 - and
        # its fair overlay is 15.81% with it against 15.73% without. The
        # border match costs 0.08pp of pixels, and is kept because the
        # geometry is what the pixels are a proxy for.
        #
        # Gated on _has_top_rule exactly as the vskip under the top rule
        # is. Without that gate the voltage-regulator fixture picks up
        # 5.3pt of air under every internal rule from a bb that excludes
        # its header - the header sits ABOVE its first rule there - and
        # pays for it: fair 23.8% -> 24.0%, matching horizontals 3/15 ->
        # 2/15, rule-to-rule +0.5pt -> +2.8pt.
        if _rules_pt:
            # Rule-driven: the air below this rule is the next row's own,
            # and it is NOT taken out of this row's extra - that extra is
            # solved below to land the rule where the source has it.
            if rule and i + 1 < len(rendered_rows):
                _rule_air_pt = _air_under_rule_pt(_rule_below_pt(i), i + 1)
        elif (
            rule
            and _has_top_rule
            and i < len(rendered_rows) - 1
            and _top_air_pt > 0.1
        ):
            _rule_air_pt = min(_top_air_pt, max(0.0, _row_extra_pt))
            _row_extra_pt -= _rule_air_pt
        _row_h_pt = _row_rise_pt(i) + _base_line_pt + max(0, _row_line_count(i) - 1) * _row_line_step(i)
        _y_pt += _pre_air_pt
        _measured = _rule_below_pt(i) if rule else None
        _ARRAYRULE_PT = _weight_of(_measured) if (rule and _rules_pt) else _rule_w_pt
        if _measured is not None and _anchor is not None:
            _target = _anchor[0] + (_measured - _anchor[1])
            # A row keeps at least its own natural line boxes. Three
            # quarters of one line was tried first and let the
            # voltage-regulator fixture's "with line" / "Quiescent Current
            # Change" / "with load" rows - three rows of text in an 8pt
            # band - print on top of each other with a rule through them.
            # A rule that cannot be reached lands a little low instead, and
            # the rows after it recover, since each aims at the anchor.
            _floor = (
                -(_row_h_pt - 0.5) if _disjoint_below(i)
                else -(_row_h_pt - _row_line_count(i) * _row_line_step(i))
            )
            _row_extra_pt = max(_floor, _target - _ARRAYRULE_PT / 2.0 - _y_pt - _row_h_pt)
        elif _measured is not None:
            # The first rule has nothing to aim at yet. The step to the
            # next row holds the rule and the air under it, so they come
            # out of this row's extra: added on top, they put the index
            # fixture's first entry 14pt low, under a rule 38pt below its
            # heading where the source leaves 8pt.
            _row_extra_pt = max(-(_row_h_pt - 0.5), _row_extra_pt - _ARRAYRULE_PT - _rule_air_pt)
        _y_pt += _row_h_pt + _row_extra_pt
        if rule:
            if _anchor is None and _measured is not None:
                _anchor = (_y_pt + _ARRAYRULE_PT / 2.0, _measured)
            _y_pt += _ARRAYRULE_PT
        _pre_air_pt = _rule_air_pt
        if abs(_row_extra_pt) > 0.01:
            # array sets a positive extra as a strut that deep in the
            # row's last cell, and a cell of several lines is already
            # deeper than that by all but its first line - the strut then
            # adds nothing. It has to reach past those lines to add the
            # extra. A negative extra is a plain \vskip and adds as is.
            _emitted_pt = _row_extra_pt
            if _row_extra_pt > 0:
                _emitted_pt += max(0, _row_line_count(i) - 1) * _row_line_step(i)
            extra = f"[{_emitted_pt:.2f}pt]"
        if rule and _rules_pt:
            rule += _sub_rules_from(_rule_below_pt(i))
        if abs(_rule_air_pt) > 0.01:
            rule = rule + _air_cmd(_rule_air_pt)
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
    # them. A blanket 2pt was tried and was too tight: "Decimal|Binary"
    # came out with the letters against the rule, worse than the source,
    # which leaves a visible gap. 4pt was the compromise that replaced it -
    # closer than LaTeX's 6pt default, which pushed the rules well outside
    # the span the text occupies. Both were one constant for every table,
    # which is the real mistake: how much air a table leaves around its
    # columns is a property OF THAT TABLE, and it is measurable from the
    # source (see _tabcolsep_pt above - each column's rule-to-rule width
    # minus the extent its own glyphs occupy). A table whose rules were
    # measured keeps its own value; one without rule geometry still gets
    # the 4pt that was tuned here.
    # A table printed on a colour is set on it: the whole tabular, rows and
    # the space between them, boxed in that colour with no margin added.
    _fill = _table_md.get("fill_rgb")
    if _fill:
        r, g, b = (max(0, min(255, int(v))) for v in _fill)
        tabular = (
            f"{{\\setlength{{\\fboxsep}}{{0pt}}\\colorbox[RGB]{{{r},{g},{b}}}{{"
            + tabular + "}}"
        )
    lines = [
        "\\begin{center}",
        f"\\renewcommand{{\\arraystretch}}{{{dynamic_arraystretch:.3f}}}",
        f"\\setlength{{\\tabcolsep}}{{{_tabcolsep_pt:.2f}pt}}",
        f"\\setlength{{\\arrayrulewidth}}{{{_rule_w_pt:.2f}pt}}",
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
