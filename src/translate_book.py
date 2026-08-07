#!/usr/bin/env python3
"""
Reusable pipeline for translating technical PDF books.

Usage:
    python translate_book.py --input book.pdf --lang ru --chapters 4
    python translate_book.py --input book.pdf --lang ru --pages 154-217
    python translate_book.py --input book.pdf --lang ru --all

Stages (each cached):
  1. extract   - Extract text from PDF pages → cache/text/*.json
  2. images    - Extract images from PDF → cache/images/
  3. translate - Translate via Claude agents (spawned by caller)
  4. assemble  - Assemble translated pages → output/*.md or output/*.tex
  5. compile   - Compile LaTeX → output/*.pdf (if LaTeX mode)

Without an Anthropic API key, step 3 produces a prompt for manual
translation via Claude Code agents. With a key, it calls the API directly.
"""

import argparse
import json
import os
import re
import sys

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF not installed. Run: pip install pymupdf")
    sys.exit(1)


CACHE_DIR = "cache"
OUTPUT_DIR = "output"


def ensure_dirs():
    for d in [
        CACHE_DIR,
        os.path.join(CACHE_DIR, "text"),
        os.path.join(CACHE_DIR, "images"),
        os.path.join(CACHE_DIR, "translations"),
        OUTPUT_DIR,
    ]:
        os.makedirs(d, exist_ok=True)


def extract_clean_text(page):
    raw = page.get_text()
    lines = raw.split("\n")
    paragraphs = []
    current = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = ""
            continue
        if current and current.endswith("-"):
            current = current[:-1] + stripped
        elif current:
            current += " " + stripped
        else:
            current = stripped
    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs)


def stage_extract(pdf_path, start, end):
    """Extract text from PDF pages."""
    cache_file = os.path.join(CACHE_DIR, "text", f"pages_{start}_{end}.json")
    if os.path.exists(cache_file):
        print(f"  [cached] {cache_file}")
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f)

    doc = fitz.open(pdf_path)
    texts = {}
    for i in range(start, end + 1):
        if i >= len(doc):
            break
        texts[str(i)] = extract_clean_text(doc[i])
    doc.close()

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(texts, f, ensure_ascii=False, indent=2)
    print(f"  Extracted {len(texts)} pages → {cache_file}")
    return texts


def stage_images(pdf_path, start, end):
    """Extract images from PDF pages."""
    img_dir = os.path.join(CACHE_DIR, "images", f"pages_{start}_{end}")
    index_file = os.path.join(img_dir, "index.json")
    if os.path.exists(index_file):
        print(f"  [cached] {index_file}")
        with open(index_file) as f:
            return json.load(f)

    os.makedirs(img_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    img_info = {}
    count = 0

    for i in range(start, end + 1):
        if i >= len(doc):
            break
        page = doc[i]
        images = page.get_images(full=True)
        for j, img in enumerate(images):
            xref = img[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                fname = f"page_{i}_img_{j}.png"
                pix.save(os.path.join(img_dir, fname))
                img_info.setdefault(str(i), []).append({
                    "file": fname,
                    "width": pix.width,
                    "height": pix.height,
                })
                count += 1
            except Exception as e:
                print(f"  Warning: page {i} img {j}: {e}")

    doc.close()
    with open(index_file, "w") as f:
        json.dump(img_info, f, indent=2)
    print(f"  Extracted {count} images → {img_dir}")
    return img_info


def stage_assemble_md(start, end, output_name, translations_dir="claude_translations"):
    """Assemble translated pages into Markdown."""
    translations = {}
    for f in sorted(os.listdir(translations_dir)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(translations_dir, f), encoding="utf-8") as fh:
            data = json.load(fh)
            for k, v in data.items():
                if start <= int(k) <= end:
                    translations[k] = v

    if not translations:
        print(f"  No translations found for pages {start}-{end}")
        return None

    md = []
    for i in range(start, end + 1):
        text = translations.get(str(i), "").strip()
        if text:
            md.append(text)
            md.append("")

    content = "\n".join(md)

    # Clean up common footer artifacts
    content = re.sub(
        r"^(?:Разд\.|Раздел|Sec\.|Гл\.|Глава)[\s\d.]+.*?\d{2,3}\s*$",
        "", content, flags=re.MULTILINE
    )
    content = re.sub(r"\n{3,}", "\n\n", content)

    out_path = os.path.join(OUTPUT_DIR, output_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Assembled {len(translations)} pages → {out_path} ({len(content)//1024} KB)")
    return out_path


def load_glossary():
    """Load glossary for translation prompts."""
    glossary_path = "glossary.json"
    if not os.path.exists(glossary_path):
        return ""
    with open(glossary_path) as f:
        g = json.load(f)
    lines = ["GLOSSARY (must use these translations):"]
    for en, info in g.get("terms", {}).items():
        if isinstance(info, dict):
            translation = info.get("translation", info.get("ru", ""))
            lines.append(f"  {en} → {translation} ({info.get('context', '')})")
    lines.append("\nDO NOT TRANSLATE (keep as-is):")
    keep = g.get("keep_as_is", {})
    for cat, vals in keep.items():
        if isinstance(vals, list):
            lines.append(f"  {cat}: {', '.join(vals[:15])}{'...' if len(vals) > 15 else ''}")
    lines.append("\nFORMATTING RULES:")
    for rule, desc in g.get("formatting_rules", {}).items():
        lines.append(f"  {rule}: {desc}")
    return "\n".join(lines)


def print_agent_commands(start, end, chapter_num, batch_size=16):
    """Print Claude Code agent commands for translation."""
    glossary = load_glossary()

    print(f"\n{'='*60}")
    print(f"Run these agents in Claude Code to translate pages {start}-{end}:")
    print(f"{'='*60}\n")

    if glossary:
        print("=== GLOSSARY FOR AGENT PROMPTS ===")
        print(glossary)
        print("=== END GLOSSARY ===\n")

    for batch_start in range(start, end + 1, batch_size):
        batch_end = min(batch_start + batch_size - 1, end)
        print(f"Agent (haiku): Translate ch{chapter_num} pages {batch_start}-{batch_end}")
        print(f"  Input:  cache/text/pages_{start}_{end}.json")
        print(f"  Output: claude_translations/ch{chapter_num}_{batch_start}_{batch_end}.json")
        print()




def main():
    parser = argparse.ArgumentParser(description="Translate technical PDF books")
    parser.add_argument("--input", "-i", required=True, help="Input PDF file")
    parser.add_argument("--lang", "-l", default="ru", help="Target language (default: ru)")
    parser.add_argument("--pages", "-p", help="Page range, e.g. 154-217")
    parser.add_argument("--chapter", "-c", type=int, help="Chapter number")
    parser.add_argument("--stage", "-s",
                        choices=["extract", "images", "translate", "assemble", "all"],
                        default="all", help="Run specific stage")
    parser.add_argument("--format", "-f", choices=["md", "tex"], default="md",
                        help="Output format")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: File not found: {args.input}")
        sys.exit(1)

    ensure_dirs()

    if args.pages:
        parts = args.pages.split("-")
        start, end = int(parts[0]), int(parts[1])
        name = f"pages_{start}_{end}"
    else:
        print("ERROR: Specify --chapter or --pages")
        sys.exit(1)

    ch_num = args.chapter or 0

    if args.stage in ("extract", "all"):
        print("\n[1/4] Extracting text...")
        stage_extract(args.input, start, end)

    if args.stage in ("images", "all"):
        print("\n[2/4] Extracting images...")
        stage_images(args.input, start, end)

    if args.stage in ("translate", "all"):
        print("\n[3/4] Translation...")
        print_agent_commands(start, end, ch_num)

    if args.stage in ("assemble", "all"):
        print("\n[4/4] Assembling output...")
        out_name = f"{ch_num:02d}_{name.lower().replace(' ', '_')}_{args.lang}.{args.format}"
        stage_assemble_md(start, end, out_name)


if __name__ == "__main__":
    main()
