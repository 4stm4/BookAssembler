#!/usr/bin/env python3
"""
Automated book translation pipeline.

Single entry point for translating any chapter of the 8088/8086 book.
Orchestrates: extract → manifest → translate → fix → validate → build → compile.

Usage:
    # Full pipeline for chapter 5:
    python3 pipeline.py --chapter 5

    # Specific stages:
    python3 pipeline.py --chapter 4 --stage validate
    python3 pipeline.py --chapter 4 --stage build
    python3 pipeline.py --chapter 4 --stage compile

    # Custom page range (not in CHAPTERS table):
    python3 pipeline.py --pages 300-350 --chapter 6
"""

import argparse
import json
import os
import re
import subprocess
import sys

try:
    import fitz
except ImportError:
    print("ERROR: pip install pymupdf")
    sys.exit(1)

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
os.chdir(PROJECT_ROOT)

PDF_FILE = "80888086micropro0000trie_2.pdf"

CHAPTERS = {
    1: (14, 30, "Introduction to Microprocessors"),
    2: (31, 88, "Software Architecture"),
    3: (89, 153, "DEBUG Program"),
    4: (154, 217, "8088/8086 Programming 1"),
    5: (218, 300, "8088/8086 Programming 2"),
    6: (301, 368, "8088/8086 Programming 3"),
    7: (369, 428, "Memory and I/O Interface"),
    8: (429, 502, "Interrupt Interface"),
    9: (503, 576, "Coprocessor and Multiprocessor"),
    10: (577, 640, "DMA and Bus Control"),
    11: (641, 712, "Serial I/O"),
    12: (713, 776, "Disk Subsystem"),
    13: (777, 836, "Display Subsystem"),
    14: (837, 918, "Advanced Processors"),
}

COMPILE_HOST = os.environ.get("COMPILE_HOST", "")
COMPILE_DIR = os.environ.get("COMPILE_DIR", "")
COMPILE_MODE = os.environ.get("COMPILE_MODE", "docker")

STAGES = ["extract", "manifest", "figures", "translate", "agents", "autofix", "validate", "build", "compile"]


def run(cmd, check=True, capture=False):
    print(f"  $ {cmd}")
    r = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    if check and r.returncode != 0:
        if capture:
            print(f"  STDERR: {r.stderr[:500]}")
        return None
    return r


def stage_extract(ch, start, end):
    """Extract text from PDF pages."""
    print("\n[1] EXTRACT — извлечение текста из PDF")
    cache_file = f"cache/text/pages_{start}_{end}.json"
    if os.path.exists(cache_file):
        print(f"  [cached] {cache_file}")
        return cache_file

    os.makedirs("cache/text", exist_ok=True)
    doc = fitz.open(PDF_FILE)
    texts = {}
    for i in range(start, end + 1):
        if i >= len(doc):
            break
        texts[str(i)] = doc[i].get_text()
    doc.close()

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(texts, f, ensure_ascii=False, indent=2)
    print(f"  Извлечено {len(texts)} страниц → {cache_file}")
    return cache_file


def stage_manifest(ch, start, end):
    """Build chapter manifest — ground truth for validation."""
    print("\n[2] MANIFEST — инвентаризация элементов главы")
    manifest_file = f"ch{ch}_manifest.json"
    run(f"python3 src/extract_chapter_manifest.py -i {PDF_FILE} -c {ch} -s {start} -e {end} -j {manifest_file}")
    return manifest_file


def stage_figures(ch, start, end):
    """Render figure pages and generate TikZ prompts."""
    print("\n[3] FIGURES — рендер страниц с фигурами + промпты для TikZ")
    manifest_file = f"ch{ch}_manifest.json"
    if not os.path.exists(manifest_file):
        stage_manifest(ch, start, end)

    with open(manifest_file) as f:
        manifest = json.load(f)

    need_tikz = [fig for fig in manifest.get("figures", [])
                 if fig["type"] not in ("debug_session", "source_listing")]
    have_tikz = [fig for fig in need_tikz
                 if os.path.exists(f"figures/fig_{fig['number'].replace('.', '_')}.tex")]
    missing = [fig for fig in need_tikz if fig not in have_tikz]

    if not missing:
        print(f"  ✅ Все {len(need_tikz)} TikZ-фигур готовы")
        return

    print(f"  Нужно нарисовать: {len(missing)} фигур")

    images_dir = f"ch{ch}_figures"
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs("figures", exist_ok=True)

    doc = fitz.open(PDF_FILE)
    rendered = set()
    for fig in missing:
        pg = fig["page"]
        if pg not in rendered:
            pix = doc[pg].get_pixmap(dpi=200)
            pix.save(os.path.join(images_dir, f"page_{pg}.png"))
            rendered.add(pg)
    doc.close()
    print(f"  Отрендерено {len(rendered)} страниц")

    # Run CV analysis on missing figures
    sys.path.insert(0, SRC_DIR)
    from diagram_extract import analyze_figure
    analyses = {}
    for fig in missing:
        try:
            analysis = analyze_figure(PDF_FILE, fig["page"], fig["number"], save_debug=True)
            analyses[fig["number"]] = analysis.to_dict()
        except Exception as e:
            print(f"  ⚠ Ошибка анализа Figure {fig['number']}: {e}")

    tasks = []
    for fig in missing:
        task = {
            "type": "figure",
            "figure": fig["number"],
            "page": fig["page"],
            "fig_type": fig["type"],
            "caption": fig.get("caption", ""),
            "image": f"{images_dir}/page_{fig['page']}.png",
            "output": f"figures/fig_{fig['number'].replace('.', '_')}.tex",
        }
        if fig["number"] in analyses:
            a = analyses[fig["number"]]
            task["primitives"] = a["primitives"]
            task["connections"] = a["connections"]
            task["reviews"] = a["reviews"]
            task["image_size"] = a["image_size"]
        tasks.append(task)

    tasks_file = f"ch{ch}_tasks.json"
    existing_tasks = []
    if os.path.exists(tasks_file):
        with open(tasks_file) as f:
            existing_tasks = [t for t in json.load(f) if t["type"] != "figure"]
    with open(tasks_file, "w") as f:
        json.dump(existing_tasks + tasks, f, ensure_ascii=False, indent=2)
    print(f"  Записано {len(tasks)} задач для фигур → {tasks_file}")


def stage_translate(ch, start, end):
    """Generate translation prompts or run translation."""
    print("\n[4] TRANSLATE — перевод")
    translations_dir = "claude_translations"
    os.makedirs(translations_dir, exist_ok=True)

    existing = {}
    for f in os.listdir(translations_dir):
        if f.startswith(f"ch{ch}") and f.endswith(".json"):
            with open(os.path.join(translations_dir, f), encoding="utf-8") as fh:
                existing.update(json.load(fh))

    translated = set(int(k) for k in existing.keys() if start <= int(k) <= end)
    all_pages = set(range(start, end + 1))
    missing = sorted(all_pages - translated)

    if not missing:
        print(f"  ✅ Все {len(all_pages)} страниц переведены")
        return

    print(f"  Переведено: {len(translated)}/{len(all_pages)}")
    print(f"  Осталось: {len(missing)} страниц")

    glossary = load_glossary_text()
    manifest_file = f"ch{ch}_manifest.json"
    manifest_context = ""
    if os.path.exists(manifest_file):
        with open(manifest_file) as f:
            manifest = json.load(f)
        manifest_context = format_manifest_for_prompt(manifest, missing)

    batch_size = 16
    tasks = []
    for i in range(0, len(missing), batch_size):
        batch = missing[i:i + batch_size]
        tasks.append({
            "type": "translate",
            "pages": batch,
            "input": f"cache/text/pages_{start}_{end}.json",
            "output": f"{translations_dir}/ch{ch}_{batch[0]}_{batch[-1]}.json",
            "glossary": glossary,
            "manifest_context": manifest_context,
        })

    tasks_file = f"ch{ch}_tasks.json"
    existing_tasks = []
    if os.path.exists(tasks_file):
        with open(tasks_file) as f:
            existing_tasks = [t for t in json.load(f) if t["type"] != "translate"]
    with open(tasks_file, "w") as f:
        json.dump(existing_tasks + tasks, f, ensure_ascii=False, indent=2)
    print(f"  Записано {len(tasks)} задач для перевода → {tasks_file}")


def load_glossary_text():
    """Load glossary as text for agent prompts."""
    if not os.path.exists("glossary.json"):
        return ""
    with open("glossary.json") as f:
        g = json.load(f)
    lines = ["СЛОВАРЬ ТЕРМИНОВ (обязательно использовать):"]
    for en, info in g.get("terms", {}).items():
        if isinstance(info, dict):
            lines.append(f"  {en} → {info['ru']} ({info.get('context', '')})")
    lines.append("\nНЕ ПЕРЕВОДИТЬ (оставить как есть):")
    keep = g.get("keep_as_is", {})
    for cat, vals in keep.items():
        if isinstance(vals, list):
            lines.append(f"  {cat}: {', '.join(vals[:20])}")
    lines.append("\nПРАВИЛА ФОРМАТИРОВАНИЯ:")
    for rule, desc in g.get("formatting_rules", {}).items():
        lines.append(f"  {rule}: {desc}")
    return "\n".join(lines)


def format_manifest_for_prompt(manifest, pages):
    """Format manifest info relevant to pages being translated."""
    lines = []
    page_set = set(str(p) for p in pages)

    order = manifest.get("element_order", {})
    for p in sorted(pages):
        sp = str(p)
        if sp in order:
            elems = order[sp]
            desc = ", ".join(f"{e['type']}:{e['id']}" for e in elems)
            lines.append(f"  Стр.{p}: {desc}")

    if lines:
        return "Порядок элементов на страницах:\n" + "\n".join(lines)
    return ""


def stage_agents(ch, start, end):
    """Print agent tasks for Claude Code to execute."""
    print("\n[5] AGENTS — задачи для Claude Code агентов")
    tasks_file = f"ch{ch}_tasks.json"
    if not os.path.exists(tasks_file):
        print("  Нет задач — всё готово")
        return

    with open(tasks_file) as f:
        tasks = json.load(f)

    if not tasks:
        print("  Нет задач — всё готово")
        return

    translate_tasks = [t for t in tasks if t["type"] == "translate"]
    figure_tasks = [t for t in tasks if t["type"] == "figure"]

    print(f"  Перевод: {len(translate_tasks)} батчей")
    print(f"  Фигуры: {len(figure_tasks)} TikZ")

    for i, t in enumerate(translate_tasks):
        pages = t["pages"]
        print(f"\n  [translate-{i+1}] Страницы {pages[0]}-{pages[-1]} ({len(pages)} стр.)")
        print(f"    Вход: {t['input']}")
        print(f"    Выход: {t['output']}")

    for i, t in enumerate(figure_tasks):
        print(f"\n  [figure-{i+1}] Figure {t['figure']} (стр. {t['page']}, {t['fig_type']})")
        print(f"    Изображение: {t['image']}")
        print(f"    Выход: {t['output']}")

    print(f"\n  Запускай: Claude Code Agent tool для каждой задачи")
    print(f"  Файл задач: {tasks_file}")


def stage_autofix(ch, start, end):
    """Auto-fix common translation issues."""
    print("\n[5] AUTOFIX — автоматическое исправление")
    translations_dir = "claude_translations"
    fixes = {}
    fix_count = 0

    all_translations = {}
    files = sorted(os.listdir(translations_dir))
    non_fixed = [f for f in files if f.startswith(f"ch{ch}") and f.endswith(".json") and "_fixed" not in f and "_autofix" not in f]
    fixed = [f for f in files if f.startswith(f"ch{ch}") and f.endswith(".json") and "_fixed" in f]
    for f in non_fixed + fixed:
        with open(os.path.join(translations_dir, f), encoding="utf-8") as fh:
            all_translations.update(json.load(fh))

    for page, text in all_translations.items():
            if not (start <= int(page) <= end):
                continue
            fixed = text
            original = text

            # Fix 1: Wrap naked DEBUG output in code blocks (only if no fences)
            if '```' not in fixed:
                fixed = wrap_naked_debug(fixed)

            # Fix 2: Wrap naked assembly in code blocks (only if no fences)
            if '```' not in fixed:
                fixed = wrap_naked_asm(fixed)

            # Fix 3: Remove duplicate markdown tables when TikZ exists
            fixed = remove_duplicate_tables(fixed, ch)

            # Fix 5: Fix subscript formatting
            fixed = fix_subscripts(fixed)

            if fixed != original:
                fixes[page] = fixed
                fix_count += 1

    if fixes:
        fix_file = os.path.join(translations_dir, f"ch{ch}_autofix.json")
        with open(fix_file, "w", encoding="utf-8") as f:
            json.dump(fixes, f, ensure_ascii=False, indent=2)
        print(f"  Исправлено {fix_count} страниц → {fix_file}")
    else:
        print("  ✅ Нечего исправлять")


def merge_debug_sessions(text):
    """Merge split DEBUG code blocks into one."""
    lines = text.split('\n')
    debug_indicators = ['C:\\DOS>DEBUG', 'C>DEBUG', 'C:\\>DEBUG']
    has_debug = any(d in text for d in debug_indicators)
    code_block_count = text.count('```')

    if not has_debug or code_block_count <= 4:
        return text

    result = []
    in_code = False
    in_debug = False
    debug_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            if in_code:
                if in_debug:
                    debug_lines.extend(code_lines)
                    code_lines = []
                    in_code = False
                    continue
                else:
                    result.append(stripped)
                    in_code = False
            else:
                if in_debug:
                    code_lines = []
                    in_code = True
                    continue
                else:
                    result.append(stripped)
                    in_code = True
                    code_lines = []
            continue

        if in_code:
            if not hasattr(merge_debug_sessions, '_cl'):
                merge_debug_sessions._cl = []
            code_lines = getattr(merge_debug_sessions, '_cl', [])
            if any(d in line for d in debug_indicators):
                in_debug = True
                debug_lines = []
            code_lines.append(line)
            merge_debug_sessions._cl = code_lines
            continue

        if in_debug and not in_code:
            if stripped and not stripped.startswith('#'):
                debug_lines.append(line)
                continue
            else:
                result.append('```')
                result.extend(debug_lines)
                result.append('```')
                debug_lines = []
                in_debug = False

        result.append(line)

    if debug_lines:
        result.append('```')
        result.extend(debug_lines)
        result.append('```')

    return '\n'.join(result)


def wrap_naked_asm(text):
    """Wrap standalone assembly instructions in code blocks."""
    asm_pattern = r'^(MOV|ADD|SUB|PUSH|POP|XCHG|LEA|LDS|LES|CMP|AND|OR|XOR|NOT|NEG|SHL|SHR|MUL|DIV|INC|DEC|ADC|SBB|IMUL|IDIV|CALL|RET|INT|JMP)\s+\S'
    lines = text.split('\n')
    result = []
    in_code = False
    asm_block = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            if asm_block:
                result.append('```asm')
                result.extend(asm_block)
                result.append('```')
                asm_block = []
            in_code = not in_code
            result.append(line)
            continue

        if in_code:
            result.append(line)
            continue

        if re.match(asm_pattern, stripped):
            asm_block.append(line)
        else:
            if asm_block:
                if len(asm_block) >= 2:
                    result.append('```asm')
                    result.extend(asm_block)
                    result.append('```')
                else:
                    result.extend(asm_block)
                asm_block = []
            result.append(line)

    if asm_block:
        if len(asm_block) >= 2:
            result.append('```asm')
            result.extend(asm_block)
            result.append('```')
        else:
            result.extend(asm_block)

    return '\n'.join(result)


def remove_duplicate_tables(text, chapter_num):
    """Remove markdown tables that duplicate existing TikZ figures."""
    fig_refs = re.findall(r'(?:Рисунок|рис\.)\s*(\d+\.\d+)', text)
    for ref in fig_refs:
        fig_file = f"figures/fig_{ref.replace('.', '_')}.tex"
        if os.path.exists(fig_file):
            lines = text.split('\n')
            table_start = None
            new_lines = []
            in_table = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('|') and stripped.endswith('|'):
                    if not in_table:
                        table_start = len(new_lines)
                        in_table = True
                    new_lines.append(line)
                else:
                    if in_table:
                        table_line_count = len(new_lines) - table_start
                        if table_line_count > 3:
                            new_lines = new_lines[:table_start]
                        in_table = False
                    new_lines.append(line)
            if in_table:
                table_line_count = len(new_lines) - table_start
                if table_line_count > 3:
                    new_lines = new_lines[:table_start]
            text = '\n'.join(new_lines)
    return text


def wrap_naked_debug(text):
    """Wrap DEBUG session output that's not inside code blocks."""
    debug_starts = ['C:\\DOS>DEBUG', 'C>DEBUG', 'C:\\>DEBUG']
    if not any(d in text for d in debug_starts):
        return text

    lines = text.split('\n')
    result = []
    in_code = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith('```'):
            in_code = not in_code
            result.append(line)
            i += 1
            continue

        if in_code:
            result.append(line)
            i += 1
            continue

        if any(d in stripped for d in debug_starts):
            debug_block = []
            while i < len(lines):
                l = lines[i].strip()
                if l.startswith('```'):
                    break
                asm_mnemonics = {'MOV','ADD','SUB','MUL','DIV','INC','DEC','AND','OR','XOR','NOT','NEG',
                                 'SHL','SHR','SAL','SAR','ROL','ROR','RCL','RCR','PUSH','POP','XCHG',
                                 'LEA','LDS','LES','CMP','TEST','JMP','CALL','RET','INT','ADC','SBB',
                                 'IMUL','IDIV','CBW','CWD','XLAT','NOP','HLT'}
                first_word = l.split()[0].upper() if l.split() else ''
                is_debug_line = (
                    any(d in l for d in debug_starts) or
                    l.startswith('-') or
                    l.startswith('—') or
                    re.match(r'^[A-Z]{2}=', l) or
                    re.match(r'^[0-9A-F]{4}:', l) or
                    l.startswith('C:\\DOS>') or
                    l.startswith('C:\\>') or
                    l in ('', 'NV UP EI PL NZ NA PO NC', 'OV UP EI PL NZ NA PO NC') or
                    re.match(r'^[A-Z]{2}\s+[0-9A-F]{4}', l) or
                    l.startswith(':') or
                    first_word in asm_mnemonics
                )
                if is_debug_line or not l:
                    debug_block.append(lines[i])
                    i += 1
                else:
                    break

            while debug_block and not debug_block[-1].strip():
                debug_block.pop()

            if debug_block:
                result.append('```')
                result.extend(debug_block)
                result.append('```')
            continue

        result.append(line)
        i += 1

    return '\n'.join(result)


def fix_subscripts(text):
    """Ensure _16, _2, _10 are proper Unicode subscripts."""
    text = re.sub(r'(?<!\w)_16\b', '₁₆', text)
    text = re.sub(r'(?<!\w)_10\b', '₁₀', text)
    text = re.sub(r'(?<!\w)_2\b', '₂', text)
    return text


def stage_validate(ch, start, end):
    """Validate translation quality."""
    print("\n[6] VALIDATE — проверка качества перевода")
    manifest_file = f"ch{ch}_manifest.json"
    manifest_arg = f"-m {manifest_file}" if os.path.exists(manifest_file) else ""
    r = run(f"python3 src/validate_chapter.py -p ch{ch} -s {start} -e {end} {manifest_arg}", check=False)
    return r.returncode == 0 if r else False


def stage_build(ch, start, end):
    """Build LaTeX from translations."""
    print("\n[7] BUILD — сборка LaTeX")
    run(f"python3 src/build_latex.py -c {ch} -s {start} -e {end}")

    book_tex = "latex_output/book.tex"
    if os.path.exists(book_tex):
        with open(book_tex, encoding="utf-8") as f:
            content = f.read()
        ch_input = f"\\input{{ch{ch:02d}}}"
        if ch_input not in content:
            content = content.replace("\\end{document}", f"{ch_input}\n\n\\end{{document}}")
            with open(book_tex, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  Добавлено {ch_input} в book.tex")


def stage_compile(ch, start, end):
    """Compile LaTeX via Docker (default) or remote SSH."""
    if COMPILE_MODE == "ssh":
        _compile_ssh(ch)
    else:
        _compile_docker(ch)


def _compile_docker(ch):
    """Compile LaTeX locally using Docker."""
    print("\n[8] COMPILE — компиляция XeLaTeX (Docker)")
    latex_dir = os.path.abspath("latex_output")
    figures_dir = os.path.abspath("figures")

    docker_cmd = (
        f"docker run --rm "
        f"-v {latex_dir}:/work "
        f"-v {figures_dir}:/work/figures "
        f"-w /work "
        f"bookassembler-xelatex "
        f"xelatex -interaction=nonstopmode book.tex"
    )
    r = run(docker_cmd, capture=True, check=False)

    pdf_src = os.path.join(latex_dir, "book.pdf")
    pdf_name = f"ch{ch}_compiled.pdf"
    if r and r.returncode == 0 and os.path.exists(pdf_src):
        import shutil
        shutil.copy2(pdf_src, pdf_name)
        print(f"  Скомпилировано → {pdf_name}")
    else:
        print("  Ошибка компиляции")
        if r and r.stdout:
            errors = [l for l in r.stdout.split('\n') if l.startswith('!')]
            for e in errors[:5]:
                print(f"    {e}")


def _compile_ssh(ch):
    """Compile LaTeX on a remote host via SSH."""
    print("\n[8] COMPILE — компиляция XeLaTeX (SSH)")
    if not COMPILE_HOST or not COMPILE_DIR:
        print("  Ошибка: установите COMPILE_HOST и COMPILE_DIR в .env")
        return

    print("  Синхронизация файлов...")
    run(f"rsync -az --delete latex_output/ {COMPILE_HOST}:{COMPILE_DIR}/")
    run(f"rsync -az figures/ {COMPILE_HOST}:{COMPILE_DIR}/figures/")

    print("  Компиляция...")
    r = run(f"ssh {COMPILE_HOST} 'cd {COMPILE_DIR} && xelatex -interaction=nonstopmode book.tex'",
            capture=True)

    if r and r.returncode == 0:
        pdf_name = f"ch{ch}_compiled.pdf"
        run(f"scp {COMPILE_HOST}:{COMPILE_DIR}/book.pdf {pdf_name}")
        print(f"  Скомпилировано → {pdf_name}")
    else:
        print("  Ошибка компиляции")
        if r and r.stdout:
            errors = [l for l in r.stdout.split('\n') if l.startswith('!')]
            for e in errors[:5]:
                print(f"    {e}")


def run_pipeline(ch, start, end, stage=None):
    """Run the full pipeline or a specific stage."""
    print(f"{'='*60}")
    print(f"PIPELINE: Глава {ch} (стр. {start}-{end})")
    print(f"{'='*60}")

    if not os.path.exists(PDF_FILE):
        print(f"ERROR: PDF не найден: {PDF_FILE}")
        sys.exit(1)

    if stage:
        stages = [stage]
    else:
        stages = STAGES

    for s in stages:
        if s == "extract":
            stage_extract(ch, start, end)
        elif s == "manifest":
            stage_manifest(ch, start, end)
        elif s == "figures":
            stage_figures(ch, start, end)
        elif s == "translate":
            stage_translate(ch, start, end)
        elif s == "agents":
            stage_agents(ch, start, end)
        elif s == "autofix":
            stage_autofix(ch, start, end)
        elif s == "validate":
            stage_validate(ch, start, end)
        elif s == "build":
            stage_build(ch, start, end)
        elif s == "compile":
            stage_compile(ch, start, end)


def main():
    parser = argparse.ArgumentParser(description="Book translation pipeline")
    parser.add_argument("--chapter", "-c", type=int, help="Chapter number")
    parser.add_argument("--pages", "-p", help="Page range (e.g. 154-217)")
    parser.add_argument("--stage", "-s", choices=STAGES, help="Run specific stage")
    parser.add_argument("--list", "-l", action="store_true", help="List chapters")
    args = parser.parse_args()

    if args.list:
        print(f"{'Ch':>3}  {'Pages':>10}  {'Count':>5}  Title")
        print("-" * 60)
        for ch, (start, end, title) in sorted(CHAPTERS.items()):
            print(f"{ch:>3}  {start:>4}-{end:<4}  {end-start+1:>5}  {title}")
        return

    if args.chapter is None and args.pages is None:
        parser.print_help()
        return

    if args.chapter and args.chapter in CHAPTERS:
        start, end, title = CHAPTERS[args.chapter]
        ch = args.chapter
    elif args.pages:
        parts = args.pages.split("-")
        start, end = int(parts[0]), int(parts[1])
        ch = args.chapter or 0
    else:
        print(f"ERROR: Unknown chapter {args.chapter}")
        print("Use --list to see available chapters")
        sys.exit(1)

    run_pipeline(ch, start, end, args.stage)


if __name__ == "__main__":
    main()
