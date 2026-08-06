#!/usr/bin/env python3
"""
Extract chapter manifest from original PDF.
Builds a structured inventory of what the chapter contains:
- Sections/subsections with exact titles
- Figures with captions and types
- Examples with numbers
- Tables (instruction tables, operand tables)
- Code blocks (DEBUG sessions, assembly listings)
- Numbered lists vs bullet lists
- Formulas

This manifest is the ground truth for validation.
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


def extract_manifest(pdf_path, start, end, chapter_num):
    doc = fitz.open(pdf_path)
    manifest = {
        "manifest_version": 1,
        "chapter": chapter_num,
        "pages": {"start": start, "end": end, "count": end - start + 1},
        "sections": [],
        "figures": [],
        "examples": [],
        "tables": [],
        "debug_sessions": [],
        "numbered_lists": [],
        "formulas": [],
        "element_order": {},
    }

    for i in range(start, end + 1):
        if i >= len(doc):
            break
        text = doc[i].get_text()

        # Sections
        for m in re.finditer(r'▲?\s*(\d+\.\d+)\s+([A-Z][A-Z\s/]+(?:INSTRUCTIONS?|SET|OPERATIONS?))', text):
            manifest["sections"].append({
                "page": i,
                "number": m.group(1),
                "title": m.group(2).strip(),
            })

        # Subsections (like "The MOV Instruction")
        for m in re.finditer(r'(?:The\s+)?(\w+)\s+Instruction\b', text):
            if m.group(1).upper() in {"MOV", "XCHG", "XLAT", "LEA", "LDS", "LES",
                                       "ADD", "ADC", "INC", "SUB", "SBB", "DEC", "NEG",
                                       "MUL", "DIV", "IMUL", "IDIV",
                                       "AND", "OR", "XOR", "NOT",
                                       "SHL", "SHR", "SAL", "SAR",
                                       "ROL", "ROR", "RCL", "RCR"}:
                manifest["sections"].append({
                    "page": i,
                    "number": "",
                    "title": f"The {m.group(1)} Instruction",
                })

        # Figures (including sub-figures like 4.13(a))
        for m in re.finditer(r'Figure\s+(\d+\.\d+)(?:\([a-c]\))?\s+(.{5,120}?)(?:\.|$)', text, re.MULTILINE):
            manifest["figures"].append({
                "page": i,
                "number": m.group(1),
                "caption": m.group(2).strip(),
                "type": classify_figure(m.group(2)),
            })

        # Examples
        for m in re.finditer(r'EXAMPLE\s+(\d+\.\d+)', text):
            manifest["examples"].append({
                "page": i,
                "number": m.group(1),
            })

        # Numbered lists (lines starting with 1. 2. 3. etc)
        numbered = re.findall(r'^\s*(\d+)\.\s+([A-Z].{10,80})', text, re.MULTILINE)
        if len(numbered) >= 3:
            first_num = int(numbered[0][0])
            if first_num == 1 and all(int(numbered[j][0]) == j + 1 for j in range(min(len(numbered), 6))):
                manifest["numbered_lists"].append({
                    "page": i,
                    "items": len(numbered),
                    "first_item": numbered[0][1].strip(),
                })

        # DEBUG sessions
        if 'C:\\DOS>DEBUG' in text or 'C>DEBUG' in text or 'C:\\>DEBUG' in text:
            manifest["debug_sessions"].append({
                "page": i,
            })

        # Instruction tables (Mnemonic | Meaning | Format pattern)
        if re.search(r'Mnemonic\s+Meaning\s+Format', text):
            manifest["tables"].append({
                "page": i,
                "type": "instruction_summary",
            })
        elif re.search(r'Destination\s+Source', text):
            manifest["tables"].append({
                "page": i,
                "type": "operand_table",
            })

        # Build element order for this page
        page_elements = []
        for m in re.finditer(r'(?:(\d+\.\d+)\s+([A-Z][A-Z\s/]+(?:INSTRUCTIONS?|SET|OPERATIONS?)))|(?:Figure\s+(\d+\.\d+))|(?:EXAMPLE\s+(\d+\.\d+))|(?:C:\\(?:DOS>|>)DEBUG)', text):
            pos = m.start()
            if m.group(1):
                page_elements.append({"pos": pos, "type": "section", "id": m.group(1)})
            elif m.group(3):
                page_elements.append({"pos": pos, "type": "figure", "id": m.group(3)})
            elif m.group(4):
                page_elements.append({"pos": pos, "type": "example", "id": m.group(4)})
            else:
                page_elements.append({"pos": pos, "type": "debug_session", "id": f"debug_p{i}"})
        page_elements.sort(key=lambda x: x["pos"])
        if page_elements:
            manifest["element_order"][str(i)] = [
                {"type": e["type"], "id": e["id"]} for e in page_elements
            ]

    doc.close()

    # Deduplicate figures by number
    seen = set()
    unique_figs = []
    for fig in manifest["figures"]:
        if fig["number"] not in seen:
            seen.add(fig["number"])
            unique_figs.append(fig)
    manifest["figures"] = unique_figs

    return manifest


def classify_figure(caption):
    cap = caption.lower()
    if cap.startswith("display") or "debug" in cap:
        return "debug_session"
    if "source program" in cap or "source listing" in cap or "source\nprogram" in cap:
        return "source_listing"
    if "block diagram" in cap or "architecture" in cap:
        return "block_diagram"
    if "result" in cap:
        return "results_table"
    if any(w in cap for w in ["shift", "rotate", "logic", "arithmetic"]):
        return "instruction_diagram"
    if "instruction" in cap and ("before" in cap or "after" in cap):
        return "register_diagram"
    if "exchange" in cap or "transfer" in cap:
        return "data_flow"
    return "general_diagram"


def print_manifest(manifest):
    print(f"{'='*60}")
    print(f"МАНИФЕСТ ГЛАВЫ {manifest['chapter']}")
    print(f"Страницы: {manifest['pages']['start']}-{manifest['pages']['end']} ({manifest['pages']['count']} стр.)")
    print(f"{'='*60}")

    print(f"\nРАЗДЕЛЫ ({len(manifest['sections'])}):")
    for s in manifest["sections"]:
        print(f"  Стр.{s['page']}: {s['number']} {s['title']}")

    print(f"\nФИГУРЫ ({len(manifest['figures'])}):")
    for f in manifest["figures"]:
        tikz = "✅" if os.path.exists(f"figures/fig_{f['number'].replace('.','_')}.tex") else "❌"
        needs_tikz = f["type"] not in ("debug_session", "source_listing")
        label = f["type"]
        if not needs_tikz:
            label += " (код)"
        print(f"  {tikz} Стр.{f['page']}: Figure {f['number']} [{label}] — {f['caption'][:50]}")

    print(f"\nПРИМЕРЫ ({len(manifest['examples'])}):")
    for e in manifest["examples"]:
        print(f"  Стр.{e['page']}: EXAMPLE {e['number']}")

    print(f"\nТАБЛИЦЫ ({len(manifest['tables'])}):")
    for t in manifest["tables"]:
        print(f"  Стр.{t['page']}: {t['type']}")

    print(f"\nDEBUG-СЕССИИ ({len(manifest['debug_sessions'])}):")
    for d in manifest["debug_sessions"]:
        print(f"  Стр.{d['page']}")

    print(f"\nНУМЕРОВАННЫЕ СПИСКИ ({len(manifest['numbered_lists'])}):")
    for n in manifest["numbered_lists"]:
        print(f"  Стр.{n['page']}: {n['items']} пунктов — {n['first_item'][:50]}")

    # Summary
    figs_need_tikz = [f for f in manifest["figures"] if f["type"] not in ("debug_session", "source_listing")]
    figs_have_tikz = sum(1 for f in figs_need_tikz if os.path.exists(f"figures/fig_{f['number'].replace('.','_')}.tex"))
    print(f"\n{'='*60}")
    print(f"ИТОГО:")
    print(f"  Разделов: {len(manifest['sections'])}")
    print(f"  Фигур: {len(manifest['figures'])} (нужен TikZ: {len(figs_need_tikz)}, есть: {figs_have_tikz})")
    print(f"  Примеров: {len(manifest['examples'])}")
    print(f"  Таблиц: {len(manifest['tables'])}")
    print(f"  DEBUG-сессий: {len(manifest['debug_sessions'])}")
    print(f"  Нумерованных списков: {len(manifest['numbered_lists'])}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--chapter", "-c", type=int, required=True)
    parser.add_argument("--start", "-s", type=int, required=True)
    parser.add_argument("--end", "-e", type=int, required=True)
    parser.add_argument("--json", "-j", help="Save manifest as JSON")
    args = parser.parse_args()

    manifest = extract_manifest(args.input, args.start, args.end, args.chapter)
    print_manifest(manifest)

    if args.json:
        with open(args.json, 'w') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"\nСохранено: {args.json}")


if __name__ == "__main__":
    main()
