#!/usr/bin/env python3
"""
Validate translated chapter quality.
Checks: untranslated text, tables, examples, code blocks, symbols, formatting,
numbered lists, duplicate tables, broken tables, problematic Unicode.

Each check returns issues with a severity: "error" or "warning".
Exit code is nonzero only when errors exist; warnings are informational.
"""

import json
import os
import re
import sys

MANIFEST_VERSION = 1

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


def _issue(page, msg, severity=SEVERITY_ERROR):
    return {"page": page, "message": msg, "severity": severity}


def load_translations(chapter_prefix, translations_dir="claude_translations"):
    translations = {}
    files = sorted(os.listdir(translations_dir))
    non_fixed = [f for f in files if f.startswith(chapter_prefix) and f.endswith(".json") and "_fixed" not in f and "_autofix" not in f]
    fixed = [f for f in files if f.startswith(chapter_prefix) and f.endswith(".json") and ("_fixed" in f or "_autofix" in f)]
    for f in non_fixed + fixed:
        with open(os.path.join(translations_dir, f), encoding="utf-8") as fh:
            translations.update(json.load(fh))
    return translations


def check_untranslated(page, text):
    issues = []
    patterns = [
        (r'\bEXAMPLE\s+\d', "EXAMPLE not translated", SEVERITY_ERROR),
        (r'\bSolution\b', "Solution not translated", SEVERITY_ERROR),
        (r'\bFigure\s+\d', "Figure not translated", SEVERITY_ERROR),
        (r'\bTable\s+\d', "Table not translated", SEVERITY_ERROR),
        (r'\bSection\s+\d', "Section not translated", SEVERITY_WARNING),
        (r'\bChapter\s+\d', "Chapter not translated", SEVERITY_WARNING),
        (r'\bNote that\b', "Note that not translated", SEVERITY_WARNING),
        (r'\bFor example\b', "For example not translated", SEVERITY_WARNING),
        (r'\bTherefore\b', "Therefore not translated", SEVERITY_WARNING),
        (r'\bHowever\b', "However not translated", SEVERITY_WARNING),
        (r'\binstruction\b', "instruction not translated", SEVERITY_WARNING),
        (r'(?<![A-Z])\b[Rr]egister\b(?!\s+[A-Z])', "register not translated", SEVERITY_WARNING),
        (r'(?<![A-Z])\bmemory\b(?!\s+(location|address|content))', "memory not translated", SEVERITY_WARNING),
        (r'(?<![A-Z])\bexecution\b', "execution not translated", SEVERITY_WARNING),
    ]
    text_no_code = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    for pattern, msg, severity in patterns:
        matches = re.findall(pattern, text_no_code)
        if matches:
            issues.append(_issue(page, f"{msg} ({len(matches)}x)", severity))
    return issues


def check_broken_text(page, text):
    issues = []
    if re.search(r'of\d{3}\s+[A-Z][a-z]', text):
        issues.append(_issue(page, "garbage text (of003 Ai)", SEVERITY_ERROR))
    if '_16' in text and '₁₆' not in text and '$' not in text:
        count = text.count('_16')
        issues.append(_issue(page, f"_16 without formatting ({count}x)", SEVERITY_WARNING))
    if '⊠' in text or '✕' in text:
        issues.append(_issue(page, "⊠/✕ instead of → or ↔", SEVERITY_WARNING))
    return issues


def check_problematic_unicode(page, text):
    issues = []
    safe_unicode = set("→←↔↵₀₁₂₃₄₅₆₇₈₉—–«»…·×÷±≤≥≠⊕∧∨¬°′″")
    for i, ch in enumerate(text):
        if ord(ch) > 0x2000 and ch not in safe_unicode:
            context = text[max(0,i-10):i+10]
            issues.append(_issue(page, f"U+{ord(ch):04X} '{ch}' may not render: ...{context}...", SEVERITY_WARNING))
            break
    return issues


def check_tables(page, text):
    issues = []
    table_indicators = [
        r'Mnemonic\s+Meaning\s+Format',
        r'Мнемоника\s+Значение\s+Формат',
        r'Destination\s+Source',
        r'Назначение\s+Источник',
        r'Flags\s+affected',
        r'Затронутые\s+флаги',
    ]
    has_table = '|' in text and text.count('|') > 4
    needs_table = any(re.search(p, text) for p in table_indicators)
    if needs_table and not has_table:
        issues.append(_issue(page, "table expected but no markdown table found", SEVERITY_ERROR))
    return issues


def check_broken_tables(page, text):
    issues = []
    lines = text.split('\n')
    table_lines = [l.strip() for l in lines if l.strip().startswith('|') and l.strip().endswith('|')]
    if not table_lines:
        return issues
    for tl in table_lines:
        if tl.replace('|', '').replace('-', '').replace(' ', '').replace(':', '') == '':
            continue
        cells = [c.strip() for c in tl.split('|')[1:-1]]
        empty = sum(1 for c in cells if not c)
        if empty > len(cells) // 2 and len(cells) > 2:
            issues.append(_issue(page, f"table with {empty}/{len(cells)} empty cells", SEVERITY_ERROR))
            break
    for tl in table_lines[:2]:
        if 'Описание' in tl and ('Источник' not in tl and 'Source' not in tl):
            if 'Назначение' in tl or 'Источник/Назначение' in tl:
                issues.append(_issue(page, "operand table with wrong headers", SEVERITY_WARNING))
                break
    return issues


def check_numbered_lists(page, text):
    issues = []
    lines = text.split('\n')
    bullet_sequence = 0
    for line in lines:
        if line.strip().startswith('- ') or line.strip().startswith('* '):
            bullet_sequence += 1
        else:
            if bullet_sequence >= 4:
                context = [l.strip() for l in lines if l.strip().startswith('- ') or l.strip().startswith('* ')]
                has_numbers = any(re.match(r'- \d+\.', c) for c in context)
                if not has_numbers:
                    first_items = context[:3]
                    issues.append(_issue(page, f"{bullet_sequence} bullets in sequence — maybe numbered list: {first_items[0][:40]}...", SEVERITY_WARNING))
            bullet_sequence = 0
    return issues


def check_duplicate_content(page, text):
    issues = []
    fig_refs = re.findall(r'(?:Рисунок|рис\.)\s*(\d+\.\d+)', text)
    for ref in fig_refs:
        fig_file = f"figures/fig_{ref.replace('.', '_')}.tex"
        if os.path.exists(fig_file):
            table_lines = [l for l in text.split('\n') if l.strip().startswith('|') and l.strip().endswith('|')]
            if len(table_lines) > 3:
                issues.append(_issue(page, f"markdown table duplicates TikZ fig_{ref.replace('.','_')}.tex", SEVERITY_WARNING))
                break
    return issues


def check_debug_sessions(page, text):
    issues = []
    code_block_count = text.count('```')
    debug_indicators = ['C:\\DOS>DEBUG', 'C>DEBUG', 'C:\\>DEBUG']
    has_debug = any(d in text for d in debug_indicators)
    if has_debug and code_block_count > 10:
        issues.append(_issue(page, f"DEBUG session split into {code_block_count//2} code blocks", SEVERITY_ERROR))
    if has_debug and code_block_count == 0:
        issues.append(_issue(page, "DEBUG session without code block", SEVERITY_ERROR))
    return issues


def check_code_blocks(page, text):
    issues = []
    asm_pattern = r'^(MOV|ADD|SUB|PUSH|POP|XCHG|LEA|LDS|LES|CMP|AND|OR|XOR|NOT|NEG|SHL|SHR|MUL|DIV|INC|DEC|ADC|SBB|IMUL|IDIV|CALL|RET|INT|JMP)\s+\S'
    lines = text.split('\n')
    in_code = False
    naked_asm = 0
    for line in lines:
        if line.strip().startswith('```'):
            in_code = not in_code
            continue
        if not in_code and re.match(asm_pattern, line.strip()):
            naked_asm += 1
    if naked_asm > 3:
        issues.append(_issue(page, f"{naked_asm} asm lines outside code blocks", SEVERITY_ERROR))
    return issues


def check_examples(page, text):
    issues = []
    example_matches = re.findall(r'(?:ПРИМЕР|Пример|EXAMPLE|Example)\s+(\d+\.\d+)', text)
    for ex in example_matches:
        if 'EXAMPLE' in text.split(ex)[0][-20:]:
            issues.append(_issue(page, f"Example {ex} not translated (EXAMPLE)", SEVERITY_ERROR))
    return issues


def check_formatting(page, text):
    issues = []
    for line in text.split('\n'):
        if len(line) > 500 and not line.startswith('|'):
            issues.append(_issue(page, f"very long line ({len(line)} chars)", SEVERITY_WARNING))
            break
    return issues


def check_figure_files(translations, chapter_prefix, manifest_path=None):
    issues = []
    ch_num = re.search(r'\d+', chapter_prefix)
    if not ch_num:
        return issues
    ch = ch_num.group()
    code_figures = set()
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
        for fig in manifest.get("figures", []):
            if fig["type"] in ("debug_session", "source_listing"):
                code_figures.add(fig["number"])

    referenced = set()
    for page, text in translations.items():
        refs = re.findall(r'(?:Рисунок|рис\.|Рис\.|Figure|Fig\.)\s*(\d+)\.(\d+)', text)
        for c, f in refs:
            if c == ch:
                ref = f"{c}.{f}"
                if ref not in code_figures:
                    referenced.add(ref)
    missing = []
    for ref in sorted(referenced, key=lambda x: float(x)):
        fig_file = f"figures/fig_{ref.replace('.', '_')}.tex"
        if not os.path.exists(fig_file):
            missing.append(ref)
    if missing:
        issues.append(_issue(None, f"missing TikZ files for figures: {', '.join(missing)}", SEVERITY_ERROR))
    return issues


def check_glossary(translations):
    issues = []
    glossary_path = "glossary.json"
    if not os.path.exists(glossary_path):
        return issues
    with open(glossary_path) as f:
        g = json.load(f)
    all_text_no_code = ""
    for page, text in translations.items():
        all_text_no_code += re.sub(r'```.*?```', '', text, flags=re.DOTALL) + "\n"
    critical_terms = {
        "EXAMPLE": ("ПРИМЕР", r'\bEXAMPLE\s+\d'),
        "Solution": ("Решение", r'\bSolution\b'),
        "Figure": ("Рисунок", r'\bFigure\s+\d'),
        "Table": ("Таблица", r'\bTable\s+\d'),
    }
    for en, (ru, pattern) in critical_terms.items():
        matches = re.findall(pattern, all_text_no_code)
        if matches:
            issues.append(_issue(None, f"glossary: '{en}' not translated as '{ru}' ({len(matches)}x)", SEVERITY_ERROR))
    return issues


def check_manifest(translations, manifest_path):
    issues = []
    if not manifest_path or not os.path.exists(manifest_path):
        return issues
    with open(manifest_path) as f:
        manifest = json.load(f)

    version = manifest.get("manifest_version", 0)
    if version < MANIFEST_VERSION:
        issues.append(_issue(None, f"manifest version {version} is outdated (current: {MANIFEST_VERSION}), regenerate with extract_chapter_manifest.py", SEVERITY_WARNING))

    all_text = "\n".join(translations.values())
    expected_examples = set()
    for ex in manifest.get("examples", []):
        expected_examples.add(ex["number"])
    for num in sorted(expected_examples, key=float):
        if not re.search(rf'(?:ПРИМЕР|Пример)\s+{re.escape(num)}', all_text):
            issues.append(_issue(None, f"Example {num} not found anywhere in translation", SEVERITY_ERROR))

    for fig in manifest.get("figures", []):
        if fig["type"] in ("debug_session", "source_listing"):
            continue
        fig_file = f"figures/fig_{fig['number'].replace('.', '_')}.tex"
        if not os.path.exists(fig_file):
            issues.append(_issue(None, f"Figure {fig['number']}: no TikZ file (type: {fig['type']})", SEVERITY_ERROR))

    for ds in manifest.get("debug_sessions", []):
        page = str(ds["page"])
        text = translations.get(page, "")
        if text and '```' not in text:
            issues.append(_issue(page, "DEBUG session without code block (manifest)", SEVERITY_ERROR))

    return issues


def validate(chapter_prefix, start, end, manifest_path=None, report_path=None):
    translations = load_translations(chapter_prefix)

    if not translations:
        print(f"ERROR: No translations found with prefix '{chapter_prefix}'")
        return -1

    print(f"{'='*60}")
    print(f"ВАЛИДАЦИЯ: {chapter_prefix} (стр. {start}-{end})")
    print(f"{'='*60}")
    print(f"Найдено страниц: {len(translations)}")
    expected = set(str(i) for i in range(start, end + 1))
    missing_pages = expected - set(translations.keys())
    if missing_pages:
        print(f"\n❌ ПРОПУЩЕННЫЕ СТРАНИЦЫ: {sorted(missing_pages, key=int)}")

    fig_issues = check_figure_files(translations, chapter_prefix, manifest_path)
    manifest_issues = check_manifest(translations, manifest_path)

    categories = {
        "Непереведённый текст": [],
        "Мусор/артефакты": [],
        "Проблемные символы Unicode": [],
        "Отсутствующие таблицы": [],
        "Кривые таблицы": [],
        "Дублирование с TikZ": [],
        "Нумерованные списки": [],
        "Код без форматирования": [],
        "DEBUG-сессии": [],
        "Примеры": [],
        "Форматирование": [],
        "Фигуры": fig_issues,
        "Глоссарий": check_glossary(translations),
        "Манифест": manifest_issues,
    }

    for page in sorted(translations.keys(), key=int):
        text = translations[page]
        categories["Непереведённый текст"].extend(check_untranslated(page, text))
        categories["Мусор/артефакты"].extend(check_broken_text(page, text))
        categories["Проблемные символы Unicode"].extend(check_problematic_unicode(page, text))
        categories["Отсутствующие таблицы"].extend(check_tables(page, text))
        categories["Кривые таблицы"].extend(check_broken_tables(page, text))
        categories["Дублирование с TikZ"].extend(check_duplicate_content(page, text))
        categories["Нумерованные списки"].extend(check_numbered_lists(page, text))
        categories["Код без форматирования"].extend(check_code_blocks(page, text))
        categories["DEBUG-сессии"].extend(check_debug_sessions(page, text))
        categories["Примеры"].extend(check_examples(page, text))
        categories["Форматирование"].extend(check_formatting(page, text))

    error_count = 0
    warning_count = 0
    for category, issues in categories.items():
        if not issues:
            continue
        errors = [i for i in issues if i["severity"] == SEVERITY_ERROR]
        warnings = [i for i in issues if i["severity"] == SEVERITY_WARNING]
        error_count += len(errors)
        warning_count += len(warnings)

        label_parts = []
        if errors:
            label_parts.append(f"{len(errors)} errors")
        if warnings:
            label_parts.append(f"{len(warnings)} warnings")
        severity_icon = "❌" if errors else "⚠️"
        print(f"\n{severity_icon} {category} ({', '.join(label_parts)}):")
        for issue in (errors + warnings)[:15]:
            icon = "  ❌" if issue["severity"] == SEVERITY_ERROR else "  ⚠️"
            pg = f"Стр.{issue['page']}: " if issue["page"] else "  "
            print(f"{icon} {pg}{issue['message']}")
        if len(issues) > 15:
            print(f"  ... и ещё {len(issues)-15}")

    if error_count == 0 and warning_count == 0:
        print("\n✅ Все проверки пройдены!")
    else:
        print(f"\n{'='*60}")
        print(f"ИТОГО: {error_count} ошибок, {warning_count} предупреждений")
        if error_count == 0:
            print("Только предупреждения — сборка разрешена.")
    print()

    total_chars_ru = 0
    total_chars_en = 0
    for text in translations.values():
        for ch in text:
            if '\u0400' <= ch <= '\u04ff':
                total_chars_ru += 1
            elif 'a' <= ch.lower() <= 'z':
                total_chars_en += 1
    pct_ru = total_chars_ru / max(total_chars_ru + total_chars_en, 1) * 100
    print(f"Русский текст: {pct_ru:.1f}%")
    print(f"Английский текст: {100-pct_ru:.1f}%")

    # JSON report
    if report_path:
        report = {
            "chapter": chapter_prefix,
            "pages": {"start": start, "end": end, "found": len(translations), "missing": sorted(missing_pages, key=int)},
            "errors": error_count,
            "warnings": warning_count,
            "categories": {},
            "russian_pct": round(pct_ru, 1),
        }
        for cat, issues in categories.items():
            if issues:
                report["categories"][cat] = issues
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Отчёт: {report_path}")

    return error_count


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", "-p", required=True, help="Chapter prefix, e.g. ch4")
    parser.add_argument("--start", "-s", type=int, required=True)
    parser.add_argument("--end", "-e", type=int, required=True)
    parser.add_argument("--manifest", "-m", help="Path to chapter manifest JSON")
    parser.add_argument("--report", "-r", help="Save JSON report to file")
    args = parser.parse_args()
    issues = validate(args.prefix, args.start, args.end, args.manifest, args.report)
    sys.exit(1 if issues else 0)
