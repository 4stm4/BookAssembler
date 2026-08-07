#!/usr/bin/env python3
"""
Automated book translation pipeline.

Single entry point for translating any chapter of a technical book.
Orchestrates: extract -> manifest -> figures -> translate -> autofix -> validate -> build -> compile.
Book-specific settings (assembly mnemonics, debug indicators, etc.) come from book_profile.

Usage:
    # Full pipeline for chapter 5:
    python3 pipeline.py --chapter 5

    # Specific stages:
    python3 pipeline.py --chapter 4 --stage validate
    python3 pipeline.py --chapter 4 --stage build
    python3 pipeline.py --chapter 4 --stage compile

    # Custom page range (not in CHAPTERS table):
    python3 pipeline.py --pages 300-350 --chapter 6

    # Resume after failure:
    python3 pipeline.py --chapter 5 --resume

    # Check status:
    python3 pipeline.py --chapter 5 --status

    # Reset a stage to re-run it:
    python3 pipeline.py --chapter 5 --reset-stage translate

    # pyjobkit modes:
    python3 pipeline.py --chapter 5 --enqueue
    python3 pipeline.py --work
    python3 pipeline.py --work-once
    python3 pipeline.py --chapter 5 --enqueue --work-once
    python3 pipeline.py --chapter 5 --jobs-status
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys

from book_profile import profile as book_profile
from state import PipelineState, validate_stage_output
from translator import TranslatorClient, TranslationRequest, Glossary

try:
    import fitz
except ImportError:
    print("ERROR: pip install pymupdf")
    sys.exit(1)

log = logging.getLogger("bookassembler")

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
PROJECT_DIR = os.environ.get("BOOKASSEMBLER_PROJECT_DIR",
                             os.path.join(PROJECT_ROOT, "project"))
os.chdir(PROJECT_DIR)

def _load_book_config(path="chapters.yaml"):
    """Load book structure from YAML config. Requires chapters.yaml."""
    config_path = os.path.join(PROJECT_DIR, path)
    if not os.path.exists(config_path):
        log.error("chapters.yaml не найден. Создайте файл конфигурации книги.")
        log.error("Пример: https://github.com/... (см. README)")
        return "", {}
    try:
        import yaml
    except ImportError:
        log.error("pip install pyyaml — требуется для загрузки chapters.yaml")
        return "", {}

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    pdf = cfg.get("book", {}).get("pdf", "")
    if not pdf:
        log.error("chapters.yaml: отсутствует book.pdf")
        return "", {}
    chapters = {}
    for ch_num, ch_data in cfg.get("chapters", {}).items():
        pages = ch_data["pages"]
        chapters[int(ch_num)] = (pages[0], pages[1], ch_data["title"])
    return pdf, chapters


PDF_FILE, CHAPTERS = _load_book_config()

COMPILE_HOST = os.environ.get("COMPILE_HOST", "")
COMPILE_DIR = os.environ.get("COMPILE_DIR", "")
COMPILE_MODE = os.environ.get("COMPILE_MODE", "docker")

STAGES = ["extract", "detect", "manifest", "figures", "translate", "autofix", "validate", "build", "compile"]


def run_cmd(cmd, check=True, capture=False):
    log.debug("$ %s", cmd)
    args = shlex.split(cmd) if isinstance(cmd, str) else cmd
    r = subprocess.run(args, capture_output=capture, text=True)
    if check and r.returncode != 0:
        if capture:
            log.warning("STDERR: %s", r.stderr[:500])
        return None
    return r


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def _pdf_hash(path, chunk_size=65536):
    """Fast hash of PDF file for cache invalidation."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _extract_page_blocks(page) -> list[dict]:
    """Extract structured blocks from a PDF page using get_text('dict').

    Returns list of dicts with keys: text, x0, y0, x1, y1, font_size, is_bold, is_mono, block_type.
    block_type: 'text' or 'image'.
    """
    data = page.get_text("dict")
    page_height = data["height"]
    page_width = data["width"]
    results = []

    for block in data["blocks"]:
        if block["type"] == 1:
            results.append({
                "text": "",
                "x0": block["bbox"][0], "y0": block["bbox"][1],
                "x1": block["bbox"][2], "y1": block["bbox"][3],
                "font_size": 0, "is_bold": False, "is_mono": False,
                "block_type": "image",
            })
            continue

        lines_text = []
        sizes = []
        bold_count = 0
        mono_count = 0
        span_count = 0

        for line in block["lines"]:
            spans_text = []
            for span in line["spans"]:
                spans_text.append(span["text"])
                if span["text"].strip():
                    sizes.append(span["size"])
                    span_count += 1
                    if span["flags"] & 16:
                        bold_count += 1
                    if span["flags"] & 8:
                        mono_count += 1
            lines_text.append("".join(spans_text))

        text = "\n".join(lines_text)
        if not text.strip():
            continue

        avg_size = sum(sizes) / len(sizes) if sizes else 0
        results.append({
            "text": text,
            "x0": block["bbox"][0], "y0": block["bbox"][1],
            "x1": block["bbox"][2], "y1": block["bbox"][3],
            "font_size": avg_size,
            "is_bold": bold_count > span_count / 2 if span_count else False,
            "is_mono": mono_count > span_count / 2 if span_count else False,
            "block_type": "text",
            "page_height": page_height,
            "page_width": page_width,
        })

    return results


def _detect_body_font_size(all_blocks: list[dict]) -> float:
    """Find the most common font size across all pages — this is body text."""
    from collections import Counter
    size_counts = Counter()
    for b in all_blocks:
        if b["block_type"] != "text":
            continue
        char_count = len(b["text"].strip())
        size_counts[round(b["font_size"])] += char_count
    if not size_counts:
        return 0
    return size_counts.most_common(1)[0][0]


def _detect_headers_footers(all_blocks: list[dict], page_count: int) -> tuple[set[str], list[re.Pattern]]:
    """Detect repeating header/footer text and patterns across pages.

    Uses block position (top/bottom 12% of page) and repetition.
    Returns (exact_texts_to_remove, regex_patterns_to_remove).
    """
    if page_count < 3:
        return set(), []

    from collections import Counter

    top_texts = Counter()
    bottom_texts = Counter()

    for b in all_blocks:
        if b["block_type"] != "text":
            continue
        text = b["text"].strip()
        if not text or len(text) > 80:
            continue
        page_h = b.get("page_height", 0)
        if not page_h:
            continue

        rel_y = b["y0"] / page_h
        if rel_y < 0.12:
            top_texts[text] += 1
        elif rel_y > 0.88:
            bottom_texts[text] += 1

    threshold = max(3, page_count * 0.3)
    hf_texts = set()

    for text, count in list(top_texts.items()) + list(bottom_texts.items()):
        if count >= threshold and not re.match(r"^[a-z]{1,4}$", text, re.IGNORECASE):
            hf_texts.add(text)

    # Auto-detect regex patterns for variable headers/footers
    # e.g. "Sec. 1-2 Title 45" or "Chap. 1 Title 23"
    hf_patterns = []
    _CANDIDATE_PATTERNS = [
        r"^Sec\.\s+\d",
        r"^Chap\.\s+\d",
        r"^Chapter\s+\d",
        r"^Section\s+\d",
    ]
    for pat_str in _CANDIDATE_PATTERNS:
        pat = re.compile(pat_str, re.IGNORECASE)
        match_count = sum(1 for t in list(top_texts) + list(bottom_texts) if pat.search(t))
        if match_count >= threshold:
            hf_patterns.append(pat)

    return hf_texts, hf_patterns


def _classify_block(block: dict, body_size: float) -> str:
    """Classify a text block: heading, body, code, caption, page_number."""
    text = block["text"].strip()

    if re.match(r"^\d{1,4}$", text):
        return "page_number"

    if block["is_mono"]:
        return "code"

    if body_size > 0:
        ratio = block["font_size"] / body_size
        if ratio > 1.15:
            return "heading"

    if re.match(r"^(Figure|Fig\.|Table|Example|FIGURE|TABLE|EXAMPLE)\s+\d", text):
        return "caption"

    return "body"


def _build_page_text(blocks: list[dict], body_size: float,
                     hf_texts: set[str], hf_patterns: list[re.Pattern] = None) -> str:
    """Build clean text from structured blocks for a single page."""
    parts = []

    for b in blocks:
        if b["block_type"] == "image":
            continue

        text = b["text"].strip()
        if not text:
            continue

        if text in hf_texts:
            continue

        page_h = b.get("page_height", 0)
        if page_h:
            rel_y = b["y0"] / page_h
            in_margin = rel_y < 0.10 or rel_y > 0.90
            if in_margin:
                if hf_patterns and any(p.search(text) for p in hf_patterns):
                    continue
                if re.match(r"^\d{1,4}$", text):
                    continue
                # Short blocks in margins with mixed content (page nums, section refs)
                if len(text) < 80 and re.search(r"(Sec\.|Chap\.|Chapter|Section)\s*\d", text, re.IGNORECASE):
                    continue

        btype = _classify_block(b, body_size)

        if btype == "page_number":
            continue

        if btype == "heading":
            parts.append(f"\n## {text}\n")
        elif btype == "code":
            parts.append(f"\n```\n{text}\n```\n")
        elif btype == "caption":
            parts.append(f"\n**{text}**\n")
        else:
            parts.append(text)

    raw = "\n".join(parts)

    # Fix hyphenated word breaks: "proc-\nessing" → "processing"
    raw = re.sub(r"(\w)-\n(\w)", r"\1\2", raw)

    # Fix dangling punctuation
    raw = re.sub(r"\n([,;:])", r" \1", raw)

    # Join broken lines within paragraphs (not inside code blocks)
    sections = re.split(r"(```.*?```)", raw, flags=re.DOTALL)
    result_parts = []
    for i, section in enumerate(sections):
        if section.startswith("```"):
            result_parts.append(section)
            continue
        lines = section.split("\n")
        merged = []
        j = 0
        while j < len(lines):
            line = lines[j]
            while (j + 1 < len(lines)
                   and line.rstrip()
                   and not line.strip().startswith("##")
                   and not line.strip().startswith("**")
                   and lines[j + 1].strip()
                   and not lines[j + 1].strip().startswith("##")
                   and not lines[j + 1].strip().startswith("**")
                   and (re.match(r"^[a-z,;(]", lines[j + 1].strip())
                        or re.search(r"[,;]\s*$", line.rstrip())
                        or re.search(r"\b(the|a|an|of|in|to|for|and|or|is|are|by|on|with|from|that|which|as|but|not|if|at|be|has|have|this|than|may|can|also|when|each|into|between|all|more|both|they|their|these|it|such)\s*$", line.rstrip(), re.IGNORECASE))):
                next_line = lines[j + 1].strip()
                line = line.rstrip() + " " + next_line
                j += 1
            merged.append(line)
            j += 1
        result_parts.append("\n".join(merged))

    raw = "".join(result_parts)

    # Collapse multiple blank lines
    raw = re.sub(r"\n{3,}", "\n\n", raw)

    return raw.strip()


def stage_extract(ch, start, end):
    """Extract text from PDF pages using structured block analysis."""
    log.info("EXTRACT — извлечение текста из PDF")
    cache_file = f"cache/text/pages_{start}_{end}.json"
    hash_file = f"cache/text/pages_{start}_{end}.pdfhash"

    if os.path.exists(cache_file):
        current_hash = _pdf_hash(PDF_FILE) if os.path.exists(PDF_FILE) else ""
        cached_hash = ""
        if os.path.exists(hash_file):
            cached_hash = open(hash_file).read().strip()
        if current_hash == cached_hash:
            log.info("cached: %s", cache_file)
            return cache_file
        else:
            log.warning("PDF изменился, перечитываю (old=%s new=%s)", cached_hash[:8], current_hash[:8])

    os.makedirs("cache/text", exist_ok=True)
    doc = fitz.open(PDF_FILE)

    # Pass 1: extract all blocks with metadata
    page_blocks = {}
    all_blocks = []
    for i in range(start, end + 1):
        if i >= len(doc):
            break
        blocks = _extract_page_blocks(doc[i])
        page_blocks[str(i)] = blocks
        all_blocks.extend(blocks)
    doc.close()

    # Pass 2: detect body font size and header/footer patterns
    body_size = _detect_body_font_size(all_blocks)
    if body_size:
        log.info("Размер основного шрифта: %d pt", body_size)

    hf_texts, hf_patterns = _detect_headers_footers(all_blocks, len(page_blocks))
    if hf_texts or hf_patterns:
        log.info("Колонтитулы: %d точных, %d паттернов", len(hf_texts), len(hf_patterns))

    # Pass 3: build clean text per page
    texts = {}
    for pg, blocks in page_blocks.items():
        texts[pg] = _build_page_text(blocks, body_size, hf_texts, hf_patterns)

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(texts, f, ensure_ascii=False, indent=2)

    if os.path.exists(PDF_FILE):
        with open(hash_file, "w") as f:
            f.write(_pdf_hash(PDF_FILE))

    log.info("Извлечено %d страниц -> %s", len(texts), cache_file)
    return cache_file


def stage_detect(ch, start, end):
    """Auto-detect book profile from extracted text if not already configured."""
    from book_profile import detect_profile, save_profile, reload_profile, _load_profile

    if _load_profile() is not None:
        log.info("DETECT — профиль книги уже существует (book_profile.yaml)")
        return

    log.info("DETECT — автоматическое определение профиля книги")

    # Load all extracted texts across all chapters for better detection
    all_texts = {}
    for ch_num, (s, e, _title) in CHAPTERS.items():
        cache_file = f"cache/text/pages_{s}_{e}.json"
        if os.path.exists(cache_file):
            with open(cache_file, encoding="utf-8") as f:
                all_texts.update(json.load(f))

    if not all_texts:
        cache_file = f"cache/text/pages_{start}_{end}.json"
        if os.path.exists(cache_file):
            with open(cache_file, encoding="utf-8") as f:
                all_texts = json.load(f)

    if not all_texts:
        log.warning("Нет извлечённого текста — пропуск detect")
        return

    book_title = ""
    try:
        import yaml
        config_path = os.path.join(PROJECT_DIR, "chapters.yaml")
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            book_title = cfg.get("book", {}).get("title", "")
    except ImportError:
        pass

    detected = detect_profile(all_texts, book_title)
    save_profile(detected)
    reload_profile()


def stage_manifest(ch, start, end):
    """Build chapter manifest — ground truth for validation."""
    log.info("MANIFEST — инвентаризация элементов главы")
    manifest_file = f"ch{ch}_manifest.json"
    script = os.path.join(PROJECT_ROOT, "src", "extract_chapter_manifest.py")
    run_cmd(f"python3 {script} -i {PDF_FILE} -c {ch} -s {start} -e {end} -j {manifest_file}")
    return manifest_file


def stage_figures(ch, start, end):
    """Render figure pages and generate TikZ prompts."""
    log.info("FIGURES — рендер страниц с фигурами + промпты для TikZ")
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
        log.info("Все %d TikZ-фигур готовы", len(need_tikz))
        return

    log.info("Нужно нарисовать: %d фигур", len(missing))

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
    log.info("Отрендерено %d страниц", len(rendered))

    sys.path.insert(0, SRC_DIR)
    from diagram_extract import analyze_figure
    analysis_cache_dir = os.path.join("cache", "diagram_analysis")
    os.makedirs(analysis_cache_dir, exist_ok=True)
    analyses = {}
    for fig in missing:
        cache_key = f"fig_{fig['number'].replace('.', '_')}.json"
        cache_path = os.path.join(analysis_cache_dir, cache_key)
        if os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                analyses[fig["number"]] = json.load(f)
            continue
        try:
            analysis = analyze_figure(PDF_FILE, fig["page"], fig["number"], save_debug=True)
            result = analysis.to_dict()
            analyses[fig["number"]] = result
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error("Ошибка анализа Figure %s: %s", fig['number'], e)

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
    log.info("Записано %d задач для фигур -> %s", len(tasks), tasks_file)


def _count_translated_pages(ch, start, end):
    """Count how many pages in range have translations on disk."""
    translations_dir = "claude_translations"
    if not os.path.isdir(translations_dir):
        return 0
    existing = {}
    for fname in os.listdir(translations_dir):
        if fname.startswith(f"ch{ch}") and fname.endswith(".json"):
            with open(os.path.join(translations_dir, fname), encoding="utf-8") as fh:
                existing.update(json.load(fh))
    return sum(1 for k in existing if start <= int(k) <= end)


def stage_translate(ch, start, end):
    """Translate pages via TranslatorClient.

    In agent mode, marks the stage as 'pending' (not done) since
    translations are produced externally by agents.
    """
    log.info("TRANSLATE — перевод")
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
        log.info("Все %d страниц переведены", len(all_pages))
        return

    log.info("Переведено: %d/%d", len(translated), len(all_pages))
    log.info("Осталось: %d страниц", len(missing))

    source_json = f"cache/text/pages_{start}_{end}.json"
    manifest_file = f"ch{ch}_manifest.json"
    manifest = None
    if os.path.exists(manifest_file):
        with open(manifest_file) as f:
            manifest = json.load(f)

    glossary = Glossary.load()

    mode = os.environ.get("TRANSLATE_MODE", "agent")
    client = TranslatorClient.create(mode)

    request = TranslationRequest.from_extracted_json(
        source_json, ch,
        page_range=(start, end),
        glossary=glossary,
        manifest=manifest,
    )
    request.pages = [p for p in request.pages if p.page_number in missing]

    result = client.translate(request)

    if result.pages:
        output = f"{translations_dir}/ch{ch}_{missing[0]}_{missing[-1]}.json"
        result.save(output)
        log.info("Переведено %d/%d страниц -> %s", result.valid_count, len(result.pages), output)
        if result.failed_pages:
            log.warning("Проблемы с %d страницами:", len(result.failed_pages))
            for p in result.failed_pages[:5]:
                log.warning("  Стр.%d: %s", p.page_number, '; '.join(p.issues))
    else:
        log.info("Задачи для агентов записаны в ch%d_tasks.json", ch)
        if mode == "agent":
            raise _AgentModePending(
                f"Переводы не готовы: создано задач, но фактических переводов нет. "
                f"Запустите агентов или используйте TRANSLATE_MODE=api."
            )


class _AgentModePending(RuntimeError):
    """Raised when agent-mode translate creates tasks but no translations exist yet."""


def stage_agents(ch, start, end):
    """Print agent tasks for Claude Code to execute."""
    log.info("AGENTS — задачи для Claude Code агентов")
    tasks_file = f"ch{ch}_tasks.json"
    if not os.path.exists(tasks_file):
        log.info("Нет задач — всё готово")
        return

    with open(tasks_file) as f:
        tasks = json.load(f)

    if not tasks:
        log.info("Нет задач — всё готово")
        return

    translate_tasks = [t for t in tasks if t["type"] == "translate"]
    figure_tasks = [t for t in tasks if t["type"] == "figure"]

    log.info("Перевод: %d батчей, Фигуры: %d TikZ", len(translate_tasks), len(figure_tasks))

    for i, t in enumerate(translate_tasks):
        pages = t.get("pages", [])
        if pages:
            log.info("[translate-%d] Страницы %d-%d (%d стр.)", i+1, pages[0], pages[-1], len(pages))
        else:
            log.info("[translate-%d] Глава %s", i+1, t.get('chapter', '?'))

    for i, t in enumerate(figure_tasks):
        log.info("[figure-%d] Figure %s (стр. %d, %s)", i+1, t['figure'], t['page'], t['fig_type'])

    log.info("Файл задач: %s", tasks_file)


def _load_translations(ch, start, end, translations_dir="claude_translations"):
    """Load translations with layered merge: original < autofix < manual_fixed."""
    if not os.path.isdir(translations_dir):
        return {}, {}

    originals = {}
    merged = {}
    files = sorted(os.listdir(translations_dir))

    base = [f for f in files if f.startswith(f"ch{ch}") and f.endswith(".json")
            and "_fixed" not in f and "_autofix" not in f]
    autofix = [f for f in files if f.startswith(f"ch{ch}") and f.endswith("_autofix.json")]
    manual = [f for f in files if f.startswith(f"ch{ch}") and f.endswith(".json")
              and "_fixed" in f]

    for layer in [base, autofix, manual]:
        for fname in layer:
            with open(os.path.join(translations_dir, fname), encoding="utf-8") as fh:
                data = json.load(fh)
                if layer is base:
                    originals.update(data)
                merged.update(data)

    filtered = {k: v for k, v in merged.items() if start <= int(k) <= end}
    orig_filtered = {k: v for k, v in originals.items() if start <= int(k) <= end}
    return filtered, orig_filtered


def _has_code_indicators(text):
    """Check if text likely contains unwrapped code (DEBUG prompts or multiple ASM-like lines)."""
    if book_profile.has_debug_session(text):
        return True
    asm_count = sum(1 for line in text.split('\n') if book_profile.is_asm_line(line))
    return asm_count >= 2


def stage_autofix(ch, start, end):
    """Auto-fix common translation issues. Writes only a diff layer."""
    log.info("AUTOFIX — автоматическое исправление")
    translations_dir = "claude_translations"

    merged, originals = _load_translations(ch, start, end, translations_dir)

    if not originals:
        log.info("Нет переводов для исправления")
        return

    fixes = {}

    for page, text in originals.items():
        if page in merged and merged[page] != originals[page]:
            continue

        fixed_text = text

        if '```' not in fixed_text and _has_code_indicators(fixed_text):
            fixed_text = wrap_naked_debug(fixed_text)
        if '```' not in fixed_text and _has_code_indicators(fixed_text):
            fixed_text = wrap_naked_asm(fixed_text)
        fixed_text = remove_duplicate_tables(fixed_text, ch)
        fixed_text = fix_subscripts(fixed_text)

        if fixed_text != text:
            fixes[page] = fixed_text

    if fixes:
        fix_file = os.path.join(translations_dir, f"ch{ch}_autofix.json")
        existing_fixes = {}
        if os.path.exists(fix_file):
            with open(fix_file, encoding="utf-8") as f:
                existing_fixes = json.load(f)
        existing_fixes.update(fixes)
        with open(fix_file, "w", encoding="utf-8") as f:
            json.dump(existing_fixes, f, ensure_ascii=False, indent=2)
        log.info("Исправлено %d страниц -> %s", len(fixes), fix_file)
    else:
        log.info("Нечего исправлять")


def merge_debug_sessions(text):
    """Merge split DEBUG code blocks into one."""
    lines = text.split('\n')
    has_debug = book_profile.has_debug_session(text)
    code_block_count = text.count('```')

    if not has_debug or code_block_count <= 4:
        return text

    result = []
    in_code = False
    in_debug = False
    debug_lines = []
    code_lines = []

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
            if book_profile.has_debug_session(line):
                in_debug = True
                debug_lines = []
            code_lines.append(line)
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

        if book_profile.is_asm_line(stripped):
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
    """Remove markdown tables that are adjacent to a figure reference with an existing TikZ file."""
    tikz_refs = set()
    for ref in re.findall(r'(?:Рисунок|рис\.)\s*(\d+\.\d+)', text):
        fig_file = f"figures/fig_{ref.replace('.', '_')}.tex"
        if os.path.exists(fig_file):
            tikz_refs.add(ref)

    if not tikz_refs:
        return text

    lines = text.split('\n')
    result = []
    table_buf = []
    pre_table_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|') and stripped.endswith('|'):
            if not table_buf:
                pre_table_lines = result[-3:] if len(result) >= 3 else result[:]
            table_buf.append(line)
        else:
            if table_buf:
                context = '\n'.join(pre_table_lines)
                near_tikz_fig = any(ref in context for ref in tikz_refs)
                if len(table_buf) > 3 and near_tikz_fig:
                    log.debug("Удалена таблица-дубликат (%d строк) рядом с TikZ фигурой", len(table_buf))
                else:
                    result.extend(table_buf)
                table_buf = []
            result.append(line)

    if table_buf:
        context = '\n'.join(pre_table_lines)
        near_tikz_fig = any(ref in context for ref in tikz_refs)
        if len(table_buf) > 3 and near_tikz_fig:
            log.debug("Удалена таблица-дубликат (%d строк) рядом с TikZ фигурой", len(table_buf))
        else:
            result.extend(table_buf)

    return '\n'.join(result)


def wrap_naked_debug(text):
    """Wrap DEBUG session output that's not inside code blocks."""
    if not book_profile.has_debug_session(text):
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

        if book_profile.has_debug_session(stripped):
            debug_block = []
            while i < len(lines):
                l = lines[i].strip()
                if l.startswith('```'):
                    break
                if book_profile.is_debug_line(l) or not l:
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
    """Ensure numeric subscripts like _16, _2, _10 are proper Unicode."""
    return book_profile.fix_subscripts(text)


def stage_validate(ch, start, end):
    """Validate translation quality. Raises on errors to block build."""
    log.info("VALIDATE — проверка качества перевода")

    # Check that translations actually exist
    translated_count = _count_translated_pages(ch, start, end)
    total_pages = end - start + 1
    if translated_count == 0:
        raise RuntimeError(
            f"Нет переводов для главы {ch} (стр. {start}-{end}). "
            "Сначала выполните этап translate."
        )

    missing_count = total_pages - translated_count
    if missing_count > 0:
        log.warning("Отсутствуют переводы для %d/%d страниц", missing_count, total_pages)

    manifest_file = f"ch{ch}_manifest.json"
    manifest_arg = f"-m {manifest_file}" if os.path.exists(manifest_file) else ""
    script = os.path.join(PROJECT_ROOT, "src", "validate_chapter.py")
    r = run_cmd(f"python3 {script} -p ch{ch} -s {start} -e {end} {manifest_arg}", check=False)
    passed = r.returncode == 0 if r else False

    if missing_count > 0:
        raise RuntimeError(
            f"Валидация: отсутствуют переводы для {missing_count} страниц. "
            "Для принудительной сборки: --stage build"
        )

    if not passed:
        raise RuntimeError(
            f"Валидация главы {ch} не пройдена. "
            "Исправьте проблемы и перезапустите с --resume. "
            "Для принудительной сборки: --stage build"
        )


def stage_build(ch, start, end):
    """Build LaTeX from translations."""
    log.info("BUILD — сборка LaTeX")
    script = os.path.join(PROJECT_ROOT, "src", "build_latex.py")
    run_cmd(f"python3 {script} -c {ch} -s {start} -e {end}")

    book_tex = "latex_output/book.tex"
    if os.path.exists(book_tex):
        with open(book_tex, encoding="utf-8") as f:
            content = f.read()
        ch_input = f"\\input{{ch{ch:02d}}}"
        if ch_input not in content:
            content = content.replace("\\end{document}", f"{ch_input}\n\n\\end{{document}}")
            with open(book_tex, "w", encoding="utf-8") as f:
                f.write(content)
            log.info("Добавлено %s в book.tex", ch_input)


def stage_compile(ch, start, end):
    """Compile LaTeX via Docker (default) or remote SSH. Raises on failure."""
    if COMPILE_MODE == "ssh":
        _compile_ssh(ch)
    else:
        _compile_docker(ch)


def _compile_docker(ch):
    """Compile LaTeX locally using Docker."""
    log.info("COMPILE — компиляция XeLaTeX (Docker)")
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
    r = run_cmd(docker_cmd, capture=True, check=False)

    pdf_src = os.path.join(latex_dir, "book.pdf")
    pdf_name = f"ch{ch}_compiled.pdf"
    if r and r.returncode == 0 and os.path.exists(pdf_src):
        shutil.copy2(pdf_src, pdf_name)
        log.info("Скомпилировано -> %s", pdf_name)
    else:
        errors_text = ""
        if r and r.stdout:
            errors = [l for l in r.stdout.split('\n') if l.startswith('!')]
            errors_text = "; ".join(errors[:5])
        raise RuntimeError(f"Ошибка компиляции Docker: {errors_text or 'xelatex failed'}")


def _validate_ssh_config():
    """Validate SSH settings before use. Returns error message or None."""
    if not COMPILE_HOST or not COMPILE_DIR:
        return "Установите COMPILE_HOST и COMPILE_DIR в .env"

    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        return ("SSH-компиляция отключена в CI/CD. "
                "Используйте COMPILE_MODE=docker или настройте "
                "GitHub Actions с Docker-контейнером")

    if "@" not in COMPILE_HOST:
        return f"COMPILE_HOST должен быть в формате user@host, получено: {COMPILE_HOST}"

    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
         COMPILE_HOST, "echo ok"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        host = COMPILE_HOST.split("@", 1)[1]
        return (f"Не удалось подключиться к {host}. "
                f"Проверьте SSH-ключи (ssh-copy-id {COMPILE_HOST}) "
                f"и доступность хоста")

    return None


def _compile_ssh(ch):
    """Compile LaTeX on a remote host via SSH."""
    log.info("COMPILE — компиляция XeLaTeX (SSH)")

    err = _validate_ssh_config()
    if err:
        raise RuntimeError(f"SSH compile: {err}")

    log.info("Синхронизация файлов...")
    run_cmd(f"rsync -az --delete latex_output/ {COMPILE_HOST}:{COMPILE_DIR}/")
    run_cmd(f"rsync -az figures/ {COMPILE_HOST}:{COMPILE_DIR}/figures/")

    log.info("Компиляция...")
    r = run_cmd(f"ssh {COMPILE_HOST} 'cd {COMPILE_DIR} && xelatex -interaction=nonstopmode book.tex'",
                capture=True)

    if r and r.returncode == 0:
        pdf_name = f"ch{ch}_compiled.pdf"
        run_cmd(f"scp {COMPILE_HOST}:{COMPILE_DIR}/book.pdf {pdf_name}")
        log.info("Скомпилировано -> %s", pdf_name)
    else:
        errors_text = ""
        if r and r.stdout:
            errors = [l for l in r.stdout.split('\n') if l.startswith('!')]
            errors_text = "; ".join(errors[:5])
        raise RuntimeError(f"Ошибка компиляции SSH: {errors_text or 'xelatex failed'}")


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

STAGE_FUNCS = {
    "extract": stage_extract,
    "detect": stage_detect,
    "manifest": stage_manifest,
    "figures": stage_figures,
    "translate": stage_translate,
    "agents": stage_agents,
    "autofix": stage_autofix,
    "validate": stage_validate,
    "build": stage_build,
    "compile": stage_compile,
}


def run_pipeline(ch, start, end, stage=None, resume=False):
    """Run the full pipeline or a specific stage, with state tracking."""
    state = PipelineState(ch)

    log.info("=" * 60)
    log.info("PIPELINE: Глава %d (стр. %d-%d)", ch, start, end)
    log.info("=" * 60)

    if not os.path.exists(PDF_FILE):
        log.error("PDF не найден: %s", PDF_FILE)
        sys.exit(1)

    if stage:
        stages = [stage]
    elif resume:
        resume_from = state.get_resume_stage(STAGES)
        if resume_from is None:
            log.info("Все этапы завершены.")
            log.info(state.summary())
            return
        stages = STAGES[STAGES.index(resume_from):]
        log.info("Продолжение с этапа: %s", resume_from)
    else:
        stages = STAGES

    log.info("\n%s", state.summary())

    exit_code = 0
    for s in stages:
        missing_deps = state.check_dependencies(s)
        if missing_deps and s != stage:
            log.info("Пропуск %s: не завершены зависимости %s", s, missing_deps)
            continue

        if not stage and state.is_done(s):
            log.debug("[%s] уже завершён, пропуск", s)
            continue

        func = STAGE_FUNCS.get(s)
        if not func:
            continue

        state.mark_running(s)
        try:
            func(ch, start, end)
            ok, err = validate_stage_output(s, ch, start, end)
            if not ok:
                state.mark_failed(s, err)
                log.error("Контракт нарушен для %s: %s", s, err)
                log.info("Используйте --resume для продолжения после исправления")
                exit_code = 1
                break
            state.mark_done(s)
        except _AgentModePending as e:
            state.mark_failed(s, str(e))
            log.warning("ОЖИДАНИЕ: %s", e)
            exit_code = 1
            break
        except Exception as e:
            state.mark_failed(s, str(e))
            log.error("ОШИБКА на этапе %s: %s", s, e)
            log.info("Используйте --resume для продолжения после исправления")
            exit_code = 1
            break

    log.info("=" * 60)
    log.info("\n%s", state.summary())
    return exit_code


# ---------------------------------------------------------------------------
# pyjobkit CLI helpers
# ---------------------------------------------------------------------------

def _enqueue_chapter(ch, start, end):
    """Enqueue pyjobkit jobs for a chapter."""
    from jobs import (
        create_engine, enqueue_translate, enqueue_build, enqueue_compile,
    )

    async def _run():
        engine = await create_engine()
        async with engine:
            for label, coro in [
                ("translate", enqueue_translate(engine, ch, start, end)),
                ("build", enqueue_build(engine, ch, start, end)),
                ("compile", enqueue_compile(engine, ch)),
            ]:
                job_id = await coro
                if job_id is None:
                    log.info("%s: уже в очереди (пропуск)", label)
                else:
                    log.info("%s: %s", label, job_id)

    asyncio.run(_run())


def _run_worker(once=False):
    """Start pyjobkit worker. Returns exit code."""
    from jobs import run_worker
    return asyncio.run(run_worker(once=once))


def _show_jobs_status(ch=None):
    """Show pyjobkit job status."""
    from jobs import get_jobs_status

    async def _run():
        status = await get_jobs_status(ch)
        log.info("Jobs total: %d", status['total'])
        for s, count in sorted(status['by_status'].items()):
            log.info("  %s: %d", s, count)
        if status['jobs']:
            log.info("Последние задачи:")
            for job in status['jobs'][-10:]:
                key = job.get('idempotency_key', '')
                st = job.get('status', '?')
                log.info("  [%s] %s (%s)", st, key, job.get('kind', ''))

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def main():
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Book translation pipeline")
    parser.add_argument("--chapter", "-c", type=int, help="Chapter number")
    parser.add_argument("--pages", "-p", help="Page range (e.g. 154-217)")
    parser.add_argument("--stage", "-s", choices=STAGES + ["agents"], help="Run specific stage")
    parser.add_argument("--list", "-l", action="store_true", help="List chapters")
    parser.add_argument("--resume", "-r", action="store_true", help="Resume from last failed/incomplete stage")
    parser.add_argument("--status", action="store_true", help="Show pipeline state for chapter")
    parser.add_argument("--reset-stage", help="Reset a stage to re-run it")

    # pyjobkit modes
    parser.add_argument("--enqueue", action="store_true", help="Enqueue jobs via pyjobkit")
    parser.add_argument("--work", action="store_true", help="Start pyjobkit worker (long-running)")
    parser.add_argument("--work-once", action="store_true", help="Process queued jobs and exit")
    parser.add_argument("--jobs-status", action="store_true", help="Show pyjobkit job status")

    args = parser.parse_args()

    if args.list:
        print(f"{'Ch':>3}  {'Pages':>10}  {'Count':>5}  Title")
        print("-" * 60)
        for ch, (start, end, title) in sorted(CHAPTERS.items()):
            print(f"{ch:>3}  {start:>4}-{end:<4}  {end-start+1:>5}  {title}")
        return 0

    if args.work:
        return _run_worker(once=False)

    if args.work_once and not args.chapter and not args.enqueue:
        return _run_worker(once=True)

    if args.jobs_status:
        _show_jobs_status(args.chapter)
        return 0

    if args.status and args.chapter:
        st = PipelineState(args.chapter)
        print(st.summary())
        return 0

    if args.reset_stage and args.chapter:
        st = PipelineState(args.chapter)
        st.reset_stage(args.reset_stage)
        print(f"Этап {args.reset_stage} сброшен для главы {args.chapter}")
        return 0

    if args.chapter is None and args.pages is None:
        parser.print_help()
        return 0

    if args.chapter and args.chapter in CHAPTERS:
        start, end, title = CHAPTERS[args.chapter]
        ch = args.chapter
    elif args.pages:
        parts = args.pages.split("-")
        start, end = int(parts[0]), int(parts[1])
        ch = args.chapter or 0
    else:
        log.error("Unknown chapter %s. Use --list to see available chapters", args.chapter)
        return 1

    if args.enqueue:
        _enqueue_chapter(ch, start, end)
        if args.work_once:
            return _run_worker(once=True)
        return 0

    exit_code = run_pipeline(ch, start, end, args.stage, args.resume) or 0
    return exit_code


def _setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


if __name__ == "__main__":
    _setup_logging()
    sys.exit(main() or 0)
