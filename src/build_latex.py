#!/usr/bin/env python3
"""
Build LaTeX chapter files from translated JSON.
Properly handles: lists, code blocks, examples, tables, math, headings.
"""

import argparse
import json
import os
import re

from book_profile import profile as book_profile

MAX_LIST_ITEM_NUMBER = 99


def md_to_latex(text, chapter_num):
    """Convert markdown-formatted translation to LaTeX."""
    lines = text.split("\n")
    result = []
    in_code = False
    in_list = False
    in_example = False
    in_table = False
    table_rows = []
    table_ncols = 0
    code_lines = []
    code_lang = ""

    for line in lines:
        stripped = line.strip()

        # Code blocks ```
        if stripped.startswith("```"):
            if in_code:
                style = "debug" if is_debug_session("\n".join(code_lines)) else ""
                if style:
                    result.append("\\begin{lstlisting}[style=debug]")
                else:
                    result.append("\\begin{lstlisting}")
                result.extend(code_lines)
                result.append("\\end{lstlisting}")
                code_lines = []
                in_code = False
            else:
                close_list_if_needed(result, in_list)
                in_list = False
                in_code = True
                code_lang = stripped[3:].strip()
            continue

        if in_code:
            code_lines.append(line)
            continue

        # Empty line
        if not stripped:
            if in_list:
                close_list_if_needed(result, in_list)
                in_list = False
            result.append("")
            continue

        # Chapter heading
        m = re.match(r"^#\s+(.+)$", stripped)
        if m:
            close_list_if_needed(result, in_list)
            in_list = False
            title = escape_text(m.group(1))
            title = re.sub(r"^\d+\.\s*—?\s*", "", title)
            result.append(f"\\setcounter{{chapter}}{{{chapter_num - 1}}}")
            result.append(f"\\chapter{{{title}}}")
            continue

        # Section heading ##
        m = re.match(r"^##\s+(.+)$", stripped)
        if m:
            close_list_if_needed(result, in_list)
            in_list = False
            if in_example:
                result.append("\\end{examplebox}")
                in_example = False
            title = escape_text(m.group(1))
            result.append(f"\\section{{{title}}}")
            continue

        # Subsection heading ### — check if it's an example
        m = re.match(r"^###\s+(.+)$", stripped)
        if m:
            close_list_if_needed(result, in_list)
            in_list = False
            sub_title = m.group(1)
            # Check if this is an Example heading
            m_ex = re.match(r"(?:Пример|ПРИМЕР|Example)\s+(\d+\.\d+)", sub_title)
            if m_ex:
                if in_example:
                    result.append("\\end{examplebox}")
                result.append("\\begin{examplebox}")
                result.append(f"\\noindent\\textbf{{ПРИМЕР {m_ex.group(1)}}}\\par\\vspace{{6pt}}")
                in_example = True
            else:
                if in_example:
                    result.append("\\end{examplebox}")
                    in_example = False
                title = escape_text(sub_title)
                result.append(f"\\subsection{{{title}}}")
            continue

        # Detect EXAMPLE start
        m = re.match(r"^(?:\*\*)?(?:ПРИМЕР|Пример|EXAMPLE)\s+(\d+\.\d+)(?:\*\*)?", stripped)
        if m:
            close_list_if_needed(result, in_list)
            in_list = False
            if in_example:
                result.append("\\end{examplebox}")
            result.append("\\begin{examplebox}")
            result.append(f"\\noindent\\textbf{{ПРИМЕР {m.group(1)}}}\\par\\vspace{{6pt}}")
            in_example = True
            continue

        # Detect Solution
        if stripped in ("Решение:", "**Решение:**", "Solution", "Solution:"):
            result.append("\\noindent\\textbf{Решение:}\\par\\vspace{4pt}")
            continue

        # End example before next section/example
        if in_example and (stripped.startswith("\\section") or
                           stripped.startswith("##") or
                           re.match(r"^(?:Использование|Инструкция|Ещё один)", stripped)):
            result.append("\\end{examplebox}")
            in_example = False

        # Bullet list items
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                result.append("\\begin{itemize}")
                in_list = "itemize"
            item_text = convert_inline(stripped[2:])
            result.append(f"  \\item {item_text}")
            continue

        # Numbered list
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m and int(m.group(1)) <= MAX_LIST_ITEM_NUMBER:
            if not in_list:
                result.append("\\begin{enumerate}")
                in_list = "enumerate"
            item_text = convert_inline(m.group(2))
            result.append(f"  \\item {item_text}")
            continue

        # Standalone assembly instruction line (centered, monospace)
        if is_standalone_asm(stripped):
            close_list_if_needed(result, in_list)
            in_list = False
            result.append(f"\\begin{{center}}\\texttt{{{escape_text(stripped)}}}\\end{{center}}")
            continue

        # Math-like formulas: PA = ...
        if re.match(r"^(?:PA|Ф\.А\.|ФА)\s*=", stripped) or re.match(r"^\(.+\)\s*[→=]", stripped):
            close_list_if_needed(result, in_list)
            in_list = False
            formula = convert_inline(stripped)
            result.append(f"\\begin{{center}}{formula}\\end{{center}}")
            continue

        # Markdown table row
        if stripped.startswith("|") and stripped.endswith("|"):
            if stripped.replace("|", "").replace("-", "").replace(" ", "").replace(":", "") == "":
                continue  # separator row
            cells = [c.strip().replace("<br>", " ").replace("<BR>", " ") for c in stripped.split("|")[1:-1]]
            if not in_table:
                table_ncols = len(cells)
                table_rows = [cells]
                in_table = True
            else:
                while len(cells) < table_ncols:
                    cells.append("")
                cells = cells[:table_ncols]
                table_rows.append(cells)
            continue
        elif in_table:
            flush_table(result, table_rows, table_ncols)
            in_table = False
            table_rows = []

        # Regular paragraph
        converted = convert_inline(stripped)
        result.append(converted)

    # Close any open environments
    if in_table:
        flush_table(result, table_rows, table_ncols)
    if in_list:
        close_list_if_needed(result, in_list)
    if in_example:
        result.append("\\end{examplebox}")

    return "\n".join(result)


def is_debug_session(text):
    """Check if code block is a DEBUG session."""
    return book_profile.has_debug_session(text)


def is_standalone_asm(line):
    """Check if line is a standalone assembly instruction to center."""
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return False
    if re.match(r"^[A-Z]:\\", stripped) or stripped.startswith("-"):
        return False
    if book_profile.is_asm_line(stripped) and len(stripped.split()) <= 4:
        return True
    return False


def close_list_if_needed(result, in_list):
    if in_list:
        result.append(f"\\end{{{in_list}}}")


def escape_text(text):
    """Escape LaTeX special characters."""
    text = text.replace("\\", "\\textbackslash{}")
    for ch in ["&", "%", "$", "#", "_", "{", "}"]:
        text = text.replace(ch, "\\" + ch)
    text = text.replace("~", "\\textasciitilde{}")
    text = text.replace("^", "\\textasciicircum{}")
    return text


def flush_table(result, rows, ncols):
    """Write accumulated table rows as LaTeX tabular."""
    if not rows:
        return
    col_spec = "|".join(["l"] * ncols)
    result.append("\\begin{center}")
    result.append(f"\\begin{{tabular}}{{|{col_spec}|}}")
    result.append("\\hline")
    for i, row in enumerate(rows):
        escaped = [escape_cell(c) for c in row]
        if i == 0:
            escaped = [f"\\textbf{{{c}}}" for c in escaped]
        result.append(" & ".join(escaped) + " \\\\")
        if i == 0:
            result.append("\\hline")
    result.append("\\hline")
    result.append("\\end{tabular}")
    result.append("\\end{center}")


def escape_cell(text):
    """Escape for table cells — preserve arrows, don't break tabular."""
    # & must NOT appear raw in cells — it's the column separator
    # But we split on | not &, so & in cell content needs escaping
    text = text.replace("&", "\\&")
    text = text.replace("→", "$\\rightarrow$")
    text = text.replace("↔", "$\\leftrightarrow$")
    text = text.replace("_", "\\_")
    text = text.replace("#", "\\#")
    text = text.replace("%", "\\%")
    return text


def convert_inline(text):
    """Convert inline markdown to LaTeX."""
    # Protect existing LaTeX commands
    protected = {}
    counter = [0]

    def protect(match):
        key = f"§§{counter[0]}§§"
        protected[key] = match.group(0)
        counter[0] += 1
        return key

    # Protect inline code first
    text = re.sub(r"`([^`]+)`", lambda m: f"\\texttt{{{escape_text(m.group(1))}}}", text)

    # Bold **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    # Italic *text*
    text = re.sub(r"\*(.+?)\*", r"\\textit{\1}", text)

    # Subscript digits — replace all Unicode subscript digits
    sub_map = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
    def sub_repl(m):
        digits = m.group(0).translate(sub_map)
        return f"$_{{{digits}}}$"
    text = re.sub(r"[₀₁₂₃₄₅₆₇₈₉]+", sub_repl, text)

    # Special Unicode symbols
    text = text.replace("↵", "$\\hookleftarrow$")
    text = text.replace("↔", "$\\leftrightarrow$")

    # Arrows
    text = text.replace("→", "$\\rightarrow$")
    text = text.replace("←", "$\\leftarrow$")

    # Escape remaining special chars (but not already escaped ones)
    for ch in ["&", "%", "#"]:
        text = re.sub(r"(?<!\\)" + re.escape(ch), "\\" + ch, text)
    text = re.sub(r"(?<!\\)_", "\\_", text)

    return text


def get_image_width(fpath):
    """Determine appropriate width for an image based on its aspect ratio."""
    try:
        from PIL import Image
        im = Image.open(fpath)
        w, h = im.size
        ratio = w / h
        if ratio > 2.5:
            return "0.9\\textwidth"
        elif ratio > 1.5:
            return "0.75\\textwidth"
        elif ratio > 1.0:
            return "0.65\\textwidth"
        elif ratio > 0.7:
            return "0.55\\textwidth"
        else:
            return "0.45\\textwidth"
    except Exception:
        return "0.7\\textwidth"


def extract_figure_captions(latex_content):
    """Extract [Рисунок X.Y — caption] lines and remove them from content."""
    captions = {}
    lines = latex_content.split("\n")
    result = []
    for line in lines:
        m = re.match(
            r"^\[(?:Рисунок|Figure)\s+(\d+)\.(\d+)\s*[—\-–:]\s*(.+)\]$",
            line.strip()
        )
        if m:
            key = f"fig_{m.group(1)}_{m.group(2)}"
            caption_text = m.group(3).rstrip("]").strip()
            captions[key] = caption_text
            continue
        # Also match without brackets
        m2 = re.match(
            r"^(?:Рисунок|Figure)\s+(\d+)\.(\d+)\s*[—\-–:]\s*(.+)$",
            line.strip()
        )
        if m2 and not line.strip().startswith("\\"):
            key = f"fig_{m2.group(1)}_{m2.group(2)}"
            caption_text = m2.group(3).strip()
            captions[key] = caption_text
            continue
        result.append(line)
    return "\n".join(result), captions


def insert_figures(latex_content, chapter_num):
    """Insert figure images/TikZ after paragraphs that first reference each figure.
    Prefers PNG images from figures/images/, falls back to TikZ .tex files.
    Uses extracted captions and appropriate image widths."""
    latex_content, captions = extract_figure_captions(latex_content)

    available = {}
    output_dir = "latex_output"
    images_dir = "figures/images"
    tikz_dir = "figures"
    images_abs = os.path.join(output_dir, images_dir)
    tikz_abs = os.path.join(output_dir, tikz_dir)
    if os.path.isdir(images_abs):
        for f in os.listdir(images_abs):
            m = re.match(r"fig_(\d+)_(\d+)\.png$", f)
            if m:
                key = f"fig_{m.group(1)}_{m.group(2)}"
                available[key] = ("image", f"{images_dir}/{f}", f"{images_abs}/{f}")
    if os.path.isdir(tikz_abs):
        for f in os.listdir(tikz_abs):
            m = re.match(r"fig_(\d+)_(\d+)\.tex$", f)
            if m:
                key = f"fig_{m.group(1)}_{m.group(2)}"
                if key not in available:
                    available[key] = ("tikz", f"{tikz_dir}/{f}", f"{tikz_abs}/{f}")

    inserted = set()
    deferred = []
    in_example = False
    lines = latex_content.split("\n")
    result = []
    for line in lines:
        if "\\begin{examplebox}" in line:
            in_example = True
        if "\\end{examplebox}" in line:
            in_example = False
            result.append(line)
            for d in deferred:
                result.append(d)
            deferred = []
            continue

        result.append(line)
        refs = re.findall(r"(?:Рисунок|рис\.|Рис\.|Figure|Fig\.)\s*(\d+)\.(\d+)", line)
        for ch, fig in refs:
            key = f"fig_{ch}_{fig}"
            if key in available and key not in inserted:
                ftype, fpath, fpath_abs = available[key]
                if ftype == "image":
                    width = get_image_width(fpath_abs)
                    caption = captions.get(key, "")
                    caption_line = f"\\caption{{{caption}}}\n" if caption else ""
                    label_line = f"\\label{{fig:{ch}.{fig}}}\n"
                    fig_code = (f"\\begin{{figure}}[H]\n"
                               f"\\centering\n"
                               f"\\includegraphics[width={width}]{{{fpath}}}\n"
                               f"{caption_line}"
                               f"{label_line}"
                               f"\\end{{figure}}")
                else:
                    fig_code = f"\\input{{{fpath.replace('.tex', '')}}}"
                if in_example:
                    deferred.append(fig_code)
                else:
                    result.append(fig_code)
                inserted.add(key)

    if inserted:
        print(f"Inserted {len(inserted)} figure references")
    if captions:
        print(f"Found {len(captions)} figure captions")
    return "\n".join(result)


def build_chapter(chapter_num, start, end, translations_dir="claude_translations"):
    """Build a LaTeX chapter file from translations."""
    translations = {}
    files = sorted(os.listdir(translations_dir))
    # Load non-fixed first, then fixed (so fixed overwrites)
    non_fixed = [f for f in files if f.endswith(".json") and "_fixed" not in f]
    fixed = [f for f in files if f.endswith(".json") and "_fixed" in f]
    for f in non_fixed + fixed:
        with open(os.path.join(translations_dir, f), encoding="utf-8") as fh:
            data = json.load(fh)
            for k, v in data.items():
                if start <= int(k) <= end:
                    translations[k] = v

    if not translations:
        print(f"No translations for pages {start}-{end}")
        return

    parts = []
    for i in range(start, end + 1):
        text = translations.get(str(i), "").strip()
        if text:
            parts.append(text)

    full_md = "\n\n".join(parts)
    latex_content = md_to_latex(full_md, chapter_num)

    # Insert figure \input{} commands where figures are referenced
    latex_content = insert_figures(latex_content, chapter_num)

    # Clean footer artifacts
    latex_content = re.sub(
        r"^(?:Разд\.|Раздел|Sec\.)[\s\d.]+.*?\d{2,3}\s*$",
        "", latex_content, flags=re.MULTILINE
    )
    latex_content = re.sub(r"\n{3,}", "\n\n", latex_content)

    out_path = os.path.join("latex_output", f"ch{chapter_num:02d}.tex")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"% Chapter {chapter_num} - auto-generated\n")
        f.write(latex_content)

    print(f"Written: {out_path} ({len(latex_content)//1024} KB)")
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", "-c", type=int, required=True)
    parser.add_argument("--start", "-s", type=int, required=True)
    parser.add_argument("--end", "-e", type=int, required=True)
    parser.add_argument("--translations", "-t", default="claude_translations")
    args = parser.parse_args()

    build_chapter(args.chapter, args.start, args.end, args.translations)


if __name__ == "__main__":
    main()
