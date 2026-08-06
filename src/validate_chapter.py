#!/usr/bin/env python3
"""
Validate translated chapter quality.
Checks: untranslated text, tables, examples, code blocks, symbols, formatting,
numbered lists, duplicate tables, broken tables, problematic Unicode.
"""

import json
import os
import re
import sys


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
        (r'\bEXAMPLE\s+\d', "EXAMPLE не переведён → ПРИМЕР"),
        (r'\bSolution\b', "Solution не переведён → Решение"),
        (r'\bFigure\s+\d', "Figure не переведён → Рисунок"),
        (r'\bTable\s+\d', "Table не переведён → Таблица"),
        (r'\bSection\s+\d', "Section не переведён → Раздел"),
        (r'\bChapter\s+\d', "Chapter не переведён → Глава"),
        (r'\bNote that\b', "Note that не переведено"),
        (r'\bFor example\b', "For example не переведено"),
        (r'\bTherefore\b', "Therefore не переведено"),
        (r'\bHowever\b', "However не переведено"),
        (r'\binstruction\b', "instruction не переведено"),
        (r'\b[Rr]egister\b(?!\s+[A-Z])', "register не переведено"),
        (r'(?<![A-Z])\bmemory\b(?!\s+(location|address|content))', "memory не переведено"),
        (r'(?<![A-Z])\bexecution\b', "execution не переведено"),
    ]
    # Filter out text inside code blocks
    text_no_code = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    for pattern, msg in patterns:
        matches = re.findall(pattern, text_no_code)
        if matches:
            issues.append(f"  Стр.{page}: {msg} ({len(matches)}x)")
    return issues


def check_broken_text(page, text):
    issues = []
    if re.search(r'of\d{3}\s+[A-Z][a-z]', text):
        issues.append(f"  Стр.{page}: мусор в тексте (of003 Ai)")
    if '_16' in text and '₁₆' not in text and '$' not in text:
        count = text.count('_16')
        issues.append(f"  Стр.{page}: _16 без форматирования ({count}x)")
    if '⊠' in text or '✕' in text:
        issues.append(f"  Стр.{page}: ⊠/✕ вместо → или ↔")
    return issues


def check_problematic_unicode(page, text):
    """Check for Unicode characters that fonts may not render."""
    issues = []
    safe_unicode = set("→←↔↵₀₁₂₃₄₅₆₇₈₉—–«»…·×÷±≤≥≠⊕∧∨¬°′″")
    for i, ch in enumerate(text):
        if ord(ch) > 0x2000 and ch not in safe_unicode:
            context = text[max(0,i-10):i+10]
            issues.append(f"  Стр.{page}: U+{ord(ch):04X} '{ch}' может не отрисоваться: ...{context}...")
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
        issues.append(f"  Стр.{page}: нужна таблица но нет markdown-таблицы")
    return issues


def check_broken_tables(page, text):
    """Check for tables with empty cells or wrong column headers."""
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
            issues.append(f"  Стр.{page}: таблица с {empty}/{len(cells)} пустыми ячейками")
            break

    # Wrong column names
    for tl in table_lines[:2]:
        if 'Описание' in tl and ('Источник' not in tl and 'Source' not in tl):
            if 'Назначение' in tl or 'Источник/Назначение' in tl:
                issues.append(f"  Стр.{page}: таблица операндов с неправильными заголовками (Описание вместо Источник)")
                break
    return issues


def check_numbered_lists(page, text):
    """Check if a numbered list in original was converted to bullets."""
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
                    issues.append(f"  Стр.{page}: {bullet_sequence} буллетов подряд — возможно должен быть нумерованный список: {first_items[0][:40]}...")
            bullet_sequence = 0
    return issues


def check_duplicate_content(page, text):
    """Check if translation contains tables/diagrams that are already in TikZ files."""
    issues = []
    fig_refs = re.findall(r'(?:Рисунок|рис\.)\s*(\d+\.\d+)', text)
    for ref in fig_refs:
        fig_file = f"figures/fig_{ref.replace('.', '_')}.tex"
        if os.path.exists(fig_file):
            table_lines = [l for l in text.split('\n') if l.strip().startswith('|') and l.strip().endswith('|')]
            if len(table_lines) > 3:
                issues.append(f"  Стр.{page}: markdown-таблица дублирует TikZ fig_{ref.replace('.','_')}.tex")
                break
    return issues


def check_debug_sessions(page, text):
    """Check that DEBUG sessions are in single code blocks, not split."""
    issues = []
    lines = text.split('\n')
    code_block_count = text.count('```')
    debug_indicators = ['C:\\DOS>DEBUG', 'C>DEBUG', 'C:\\>DEBUG']
    has_debug = any(d in text for d in debug_indicators)

    if has_debug and code_block_count > 10:
        issues.append(f"  Стр.{page}: DEBUG-сессия разбита на {code_block_count//2} блоков кода")

    if has_debug and code_block_count == 0:
        issues.append(f"  Стр.{page}: DEBUG-сессия без блока кода")
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
        issues.append(f"  Стр.{page}: {naked_asm} строк asm вне блоков кода")
    return issues


def check_examples(page, text):
    issues = []
    example_matches = re.findall(r'(?:ПРИМЕР|Пример|EXAMPLE|Example)\s+(\d+\.\d+)', text)
    for ex in example_matches:
        if 'EXAMPLE' in text.split(ex)[0][-20:]:
            issues.append(f"  Стр.{page}: Пример {ex} не переведён (EXAMPLE)")
    return issues


def check_formatting(page, text):
    issues = []
    for line in text.split('\n'):
        if len(line) > 500 and not line.startswith('|'):
            issues.append(f"  Стр.{page}: очень длинная строка ({len(line)} символов)")
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
        issues.append(f"  Нет TikZ-файлов для фигур: {', '.join(missing)}")
    else:
        if referenced:
            print(f"  ✅ Все {len(referenced)} фигур имеют .tex файлы")
    return issues


def check_glossary(translations):
    """Check that glossary terms are translated consistently."""
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
            issues.append(f"  Глоссарий: '{en}' не переведён как '{ru}' ({len(matches)}x)")

    return issues


def check_manifest(translations, manifest_path):
    """Validate translation against chapter manifest (ground truth)."""
    issues = []
    if not manifest_path or not os.path.exists(manifest_path):
        return issues

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Check examples exist somewhere in the translation (not per-page, pages shift)
    all_text = "\n".join(translations.values())
    expected_examples = set()
    for ex in manifest.get("examples", []):
        expected_examples.add(ex["number"])
    for num in sorted(expected_examples, key=float):
        if not re.search(rf'(?:ПРИМЕР|Пример)\s+{re.escape(num)}', all_text):
            issues.append(f"  Пример {num} не найден нигде в переводе")

    # Check figures that need TikZ
    for fig in manifest.get("figures", []):
        if fig["type"] in ("debug_session", "source_listing"):
            continue
        fig_file = f"figures/fig_{fig['number'].replace('.', '_')}.tex"
        if not os.path.exists(fig_file):
            issues.append(f"  Figure {fig['number']}: нет TikZ-файла (тип: {fig['type']})")

    # Check DEBUG sessions are in code blocks
    for ds in manifest.get("debug_sessions", []):
        page = str(ds["page"])
        text = translations.get(page, "")
        if text and '```' not in text:
            issues.append(f"  Стр.{page}: DEBUG-сессия без блока кода")

    return issues


def validate(chapter_prefix, start, end, manifest_path=None):
    translations = load_translations(chapter_prefix)

    if not translations:
        print(f"ERROR: No translations found with prefix '{chapter_prefix}'")
        return

    print(f"{'='*60}")
    print(f"ВАЛИДАЦИЯ: {chapter_prefix} (стр. {start}-{end})")
    print(f"{'='*60}")
    print(f"Найдено страниц: {len(translations)}")
    expected = set(str(i) for i in range(start, end + 1))
    missing = expected - set(translations.keys())
    if missing:
        print(f"\n❌ ПРОПУЩЕННЫЕ СТРАНИЦЫ: {sorted(missing, key=int)}")

    fig_issues = check_figure_files(translations, chapter_prefix, manifest_path)
    manifest_issues = check_manifest(translations, manifest_path)

    all_issues = {
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
        all_issues["Непереведённый текст"].extend(check_untranslated(page, text))
        all_issues["Мусор/артефакты"].extend(check_broken_text(page, text))
        all_issues["Проблемные символы Unicode"].extend(check_problematic_unicode(page, text))
        all_issues["Отсутствующие таблицы"].extend(check_tables(page, text))
        all_issues["Кривые таблицы"].extend(check_broken_tables(page, text))
        all_issues["Дублирование с TikZ"].extend(check_duplicate_content(page, text))
        all_issues["Нумерованные списки"].extend(check_numbered_lists(page, text))
        all_issues["Код без форматирования"].extend(check_code_blocks(page, text))
        all_issues["DEBUG-сессии"].extend(check_debug_sessions(page, text))
        all_issues["Примеры"].extend(check_examples(page, text))
        all_issues["Форматирование"].extend(check_formatting(page, text))

    total = 0
    for category, issues in all_issues.items():
        if issues:
            print(f"\n❌ {category} ({len(issues)}):")
            for issue in issues[:15]:
                print(issue)
            if len(issues) > 15:
                print(f"  ... и ещё {len(issues)-15}")
            total += len(issues)

    if total == 0:
        print("\n✅ Все проверки пройдены!")
    else:
        print(f"\n{'='*60}")
        print(f"ИТОГО: {total} проблем")
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
    return total


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", "-p", required=True, help="Chapter prefix, e.g. ch4")
    parser.add_argument("--start", "-s", type=int, required=True)
    parser.add_argument("--end", "-e", type=int, required=True)
    parser.add_argument("--manifest", "-m", help="Path to chapter manifest JSON")
    args = parser.parse_args()
    issues = validate(args.prefix, args.start, args.end, args.manifest)
    sys.exit(1 if issues else 0)
