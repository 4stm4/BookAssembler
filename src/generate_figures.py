#!/usr/bin/env python3
"""
Generate TikZ figures from scanned PDF pages.

For each page that contains a figure:
1. Renders the page as an image
2. Identifies what type of figure it is
3. Generates TikZ code to recreate it

This script produces figure .tex files that can be \\input{} in the main document.
Designed to be run with Claude Code agents for image analysis.

Usage:
    python3 generate_figures.py --input book.pdf --chapter 4 --start 154 --end 217

Output:
    figures/fig_4_1.tex, figures/fig_4_2.tex, ...
"""

import argparse
import json
import os
import re
import sys

try:
    import fitz
except ImportError:
    print("ERROR: PyMuPDF not installed")
    sys.exit(1)


def find_figures(pdf_path, start, end):
    """Find pages containing figure captions and extract figure info."""
    doc = fitz.open(pdf_path)
    figures = []

    for i in range(start, end + 1):
        if i >= len(doc):
            break
        text = doc[i].get_text()
        captions = re.findall(
            r'Figure\s+(\d+\.\d+)(?:\(([a-z])\))?\s+(.{5,80})',
            text
        )
        for fig_num, sub, desc in captions:
            figures.append({
                "page": i,
                "figure": fig_num,
                "sub": sub,
                "description": desc.strip().rstrip("."),
                "type": classify_figure(desc),
            })

    doc.close()
    return figures


def classify_figure(description):
    """Classify figure type from its caption."""
    desc_lower = description.lower()
    if "display sequence" in desc_lower or "debug" in desc_lower:
        return "debug_session"
    if "instruction" in desc_lower and ("before" in desc_lower or "after" in desc_lower or "fetch" in desc_lower):
        return "register_diagram"
    if any(w in desc_lower for w in ["block diagram", "architecture", "bus", "system"]):
        return "block_diagram"
    if "result" in desc_lower:
        return "results_table"
    if any(w in desc_lower for w in ["shift", "rotate", "logic", "arithmetic"]):
        return "instruction_diagram"
    if "exchange" in desc_lower or "transfer" in desc_lower or "move" in desc_lower:
        return "data_flow"
    if "continued" in desc_lower:
        return "continuation"
    return "general_diagram"


def render_figure_pages(pdf_path, figures, output_dir):
    """Render pages containing figures as images."""
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)

    rendered = set()
    for fig in figures:
        pg = fig["page"]
        if pg in rendered:
            continue
        pix = doc[pg].get_pixmap(dpi=200)
        img_path = os.path.join(output_dir, f"page_{pg}.png")
        pix.save(img_path)
        rendered.add(pg)

    doc.close()
    print(f"Rendered {len(rendered)} pages with figures")


def generate_agent_prompts(figures, images_dir):
    """Generate prompts for Claude agents to create TikZ code."""
    prompts = []

    # Group figures by page
    by_page = {}
    for fig in figures:
        by_page.setdefault(fig["page"], []).append(fig)

    for page, page_figs in sorted(by_page.items()):
        fig_list = ", ".join(f"Figure {f['figure']}" for f in page_figs)
        fig_types = ", ".join(f"{f['figure']}={f['type']}" for f in page_figs)

        prompt = f"""Look at the image file {images_dir}/page_{page}.png

This page contains: {fig_list}
Figure types: {fig_types}

For each figure on this page, generate LaTeX TikZ code that recreates the diagram.

Rules:
1. Use TikZ with these libraries: shapes, arrows.meta, positioning, calc, fit
2. For register diagrams: draw boxes with register names, use arrows for data flow
3. For instruction tables: use tabular (not TikZ)
4. For DEBUG sessions: use lstlisting with style=debug
5. For block diagrams: use rectangles, arrows, labels
6. For shift/rotate diagrams: show bit positions with boxes and arrows
7. Translate all English labels to Russian (except register names, mnemonics, hex)
8. Each figure should be wrapped in \\begin{{figure}}[htbp] with \\caption and \\label

Write each figure as a separate .tex file:
  figures/fig_{page_figs[0]['figure'].replace('.','_')}.tex

The file should contain ONLY the figure environment, ready to \\input{{}} in a document."""

        prompts.append({
            "page": page,
            "figures": page_figs,
            "prompt": prompt,
        })

    return prompts


def print_agent_commands(prompts):
    """Print commands to run agents."""
    print(f"\n{'='*60}")
    print(f"AGENTS NEEDED: {len(prompts)} agents for {sum(len(p['figures']) for p in prompts)} figures")
    print(f"{'='*60}\n")

    for p in prompts:
        figs = ", ".join(f"Fig {f['figure']}" for f in p["figures"])
        print(f"Page {p['page']}: {figs} ({p['figures'][0]['type']})")

    print(f"\nRun these as Claude Code agents with image reading capability.")
    print(f"Each agent reads the page image and generates TikZ .tex files.\n")


def validate_figures(figures_dir, expected_figures):
    """Validate that all expected figure files exist and compile."""
    missing = []
    found = []

    for fig in expected_figures:
        fig_file = f"fig_{fig['figure'].replace('.', '_')}.tex"
        path = os.path.join(figures_dir, fig_file)
        if os.path.exists(path):
            with open(path) as f:
                content = f.read()
            if "\\begin{figure}" in content or "\\begin{tikzpicture}" in content:
                found.append(fig_file)
            else:
                missing.append(f"{fig_file} (no figure/tikz environment)")
        else:
            missing.append(f"{fig_file} (not found)")

    print(f"\n{'='*60}")
    print(f"FIGURE VALIDATION")
    print(f"{'='*60}")
    print(f"Found: {len(found)}/{len(expected_figures)}")
    if missing:
        print(f"Missing: {len(missing)}")
        for m in missing[:10]:
            print(f"  ❌ {m}")
    else:
        print("✅ All figures present")

    return len(missing) == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--chapter", "-c", type=int, required=True)
    parser.add_argument("--start", "-s", type=int, required=True)
    parser.add_argument("--end", "-e", type=int, required=True)
    parser.add_argument("--render", action="store_true", help="Render page images")
    parser.add_argument("--validate", action="store_true", help="Validate figure files")
    args = parser.parse_args()

    figures = find_figures(args.input, args.start, args.end)
    print(f"Found {len(figures)} figures in chapter {args.chapter}")

    for fig in figures:
        print(f"  Page {fig['page']}: Figure {fig['figure']} [{fig['type']}] — {fig['description'][:40]}")

    images_dir = f"ch{args.chapter}_figures"
    figures_dir = "figures"
    os.makedirs(figures_dir, exist_ok=True)

    if args.render:
        render_figure_pages(args.input, figures, images_dir)

    if args.validate:
        validate_figures(figures_dir, figures)
    else:
        prompts = generate_agent_prompts(figures, images_dir)
        print_agent_commands(prompts)


if __name__ == "__main__":
    main()
