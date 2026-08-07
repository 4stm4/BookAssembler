"""
Translation service abstraction.

Provides a typed contract between the pipeline and whatever performs
the actual translation (Claude API, Claude Code agents, manual).

    request = TranslationRequest(pages={...}, chapter=4, ...)
    client  = TranslatorClient.create("api")   # or "agent"
    result  = client.translate(request)
    result.save("claude_translations/ch4_154_170.json")
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

from book_profile import profile as book_profile

log = logging.getLogger("bookassembler")


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass
class PageContent:
    """One page of source material with its structural metadata."""
    page_number: int
    text: str
    has_code: bool = False
    has_table: bool = False
    has_figure_ref: str | None = None
    has_debug_session: bool = False
    element_order: list[dict] | None = None


@dataclass
class TranslationRequest:
    """Input contract — everything the translator needs for one batch."""
    pages: list[PageContent]
    chapter: int
    glossary: Glossary | None = None
    manifest_context: str = ""
    target_lang: str = "ru"

    @classmethod
    def from_extracted_json(cls, json_path: str, chapter: int,
                            page_range: tuple[int, int] | None = None,
                            glossary: Glossary | None = None,
                            manifest: dict | None = None) -> TranslationRequest:
        with open(json_path, encoding="utf-8") as f:
            raw: dict[str, str] = json.load(f)

        pages = []
        for page_str, text in raw.items():
            pg = int(page_str)
            if page_range and not (page_range[0] <= pg <= page_range[1]):
                continue
            pages.append(_classify_page(pg, text, manifest))

        pages.sort(key=lambda p: p.page_number)

        manifest_context = ""
        if manifest:
            manifest_context = _format_manifest(manifest, [p.page_number for p in pages])

        return cls(
            pages=pages,
            chapter=chapter,
            glossary=glossary,
            manifest_context=manifest_context,
        )


@dataclass
class TranslatedPage:
    """One translated page with quality signals."""
    page_number: int
    text: str
    issues: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.issues) == 0


@dataclass
class TranslationResult:
    """Output contract — validated translation batch."""
    pages: list[TranslatedPage]
    chapter: int

    @property
    def valid_count(self) -> int:
        return sum(1 for p in self.pages if p.is_valid)

    @property
    def all_valid(self) -> bool:
        return all(p.is_valid for p in self.pages)

    @property
    def failed_pages(self) -> list[TranslatedPage]:
        return [p for p in self.pages if not p.is_valid]

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {str(p.page_number): p.text for p in self.pages if p.is_valid}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def to_dict(self) -> dict[str, str]:
        return {str(p.page_number): p.text for p in self.pages}


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------

@dataclass
class Glossary:
    """Terminology management."""
    terms: dict[str, dict]
    keep_as_is: dict[str, list[str]]
    formatting_rules: dict[str, str]

    @classmethod
    def load(cls, path: str = "glossary.json") -> Glossary | None:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            g = json.load(f)
        return cls(
            terms=g.get("terms", {}),
            keep_as_is=g.get("keep_as_is", {}),
            formatting_rules=g.get("formatting_rules", {}),
        )

    def to_prompt(self) -> str:
        lines = ["GLOSSARY (must use these translations):"]
        for en, info in self.terms.items():
            if isinstance(info, dict):
                translation = info.get("translation", info.get("ru", ""))
                lines.append(f"  {en} → {translation} ({info.get('context', '')})")
        lines.append("\nDO NOT TRANSLATE (keep as-is):")
        for cat, vals in self.keep_as_is.items():
            if isinstance(vals, list):
                lines.append(f"  {cat}: {', '.join(vals[:20])}")
        lines.append("\nFORMATTING RULES:")
        for rule, desc in self.formatting_rules.items():
            lines.append(f"  {rule}: {desc}")
        return "\n".join(lines)

    def check_compliance(self, text: str) -> list[str]:
        """Check that critical terms are translated per glossary."""
        from validate_chapter import CRITICAL_UNTRANSLATED
        issues = []
        text_no_code = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        for pattern, msg in CRITICAL_UNTRANSLATED:
            if re.search(pattern, text_no_code):
                issues.append(msg)
        return issues

    def collect_term_candidates(self, text: str):
        """Find English technical terms not in the glossary. Returns a set of candidates."""
        text_no_code = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        known_en = set(self.terms.keys())
        keep_flat = set()
        for vals in self.keep_as_is.values():
            if isinstance(vals, list):
                keep_flat.update(v.lower() for v in vals)

        tech_patterns = [
            r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b',
            r'\b([a-z]+\s+(?:register|flag|instruction|controller|interrupt|buffer|port|bus|mode|segment|stack|pointer|address))\b',
        ]
        candidates = set()
        for pattern in tech_patterns:
            for m in re.finditer(pattern, text_no_code):
                term = m.group(1).strip()
                if (term.lower() not in known_en and
                    term.lower() not in keep_flat and
                    len(term) > 4):
                    candidates.add(term)
        return candidates

    def flush_term_suggestions(self, all_candidates: set[str],
                               suggestions_path: str = "glossary_suggestions.json"):
        """Write accumulated term candidates to disk in one pass."""
        if not all_candidates:
            return

        existing = {}
        if os.path.exists(suggestions_path):
            with open(suggestions_path, encoding="utf-8") as f:
                existing = json.load(f)

        for term in all_candidates:
            if term not in existing:
                existing[term] = {"count": 1, "status": "pending"}
            else:
                existing[term]["count"] = existing[term].get("count", 0) + 1

        with open(suggestions_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    def suggest_new_terms(self, text: str, suggestions_path: str = "glossary_suggestions.json"):
        """Convenience wrapper for single-page use."""
        candidates = self.collect_term_candidates(text)
        self.flush_term_suggestions(candidates, suggestions_path)


# ---------------------------------------------------------------------------
# Validators (replace regex autofix with structured checks)
# ---------------------------------------------------------------------------

_LANG_CHAR_RANGES = {
    "ru": ('\u0400', '\u04ff'),
    "uk": ('\u0400', '\u04ff'),
    "zh": ('\u4e00', '\u9fff'),
    "ja": ('\u3040', '\u30ff'),
    "ko": ('\uac00', '\ud7af'),
    "ar": ('\u0600', '\u06ff'),
    "hi": ('\u0900', '\u097f'),
}


def validate_translation(page: PageContent, translated_text: str,
                         glossary: Glossary | None = None,
                         target_lang: str = "ru") -> list[str]:
    """Validate a single page translation. Returns list of issues."""
    issues = []

    if not translated_text or not translated_text.strip():
        issues.append("Empty translation")
        return issues

    # 1. Ratio check: translation should contain target language characters
    char_range = _LANG_CHAR_RANGES.get(target_lang)
    if char_range:
        lo, hi = char_range
        text_no_code = re.sub(r'```.*?```', '', translated_text, flags=re.DOTALL)
        target_chars = sum(1 for c in text_no_code if lo <= c <= hi)
        en_chars = sum(1 for c in text_no_code if 'a' <= c.lower() <= 'z')
        total = target_chars + en_chars
        if total > 50 and target_chars / total < 0.4:
            issues.append(f"Low target language ratio ({target_chars}/{total} = {target_chars/total:.0%})")

    # 2. Code blocks: if source has code, translation should have code blocks
    if page.has_code or page.has_debug_session:
        if '```' not in translated_text:
            issues.append("Source has code but translation has no code blocks")

    # 3. Glossary compliance + auto-suggest
    if glossary:
        glossary_issues = glossary.check_compliance(translated_text)
        issues.extend(glossary_issues)
        glossary.suggest_new_terms(page.text)

    # 4. Structural issues
    if len(translated_text) < len(page.text) * 0.3:
        issues.append("Перевод подозрительно короткий (< 30% от оригинала)")

    # 5. Broken formatting
    open_fences = translated_text.count('```')
    if open_fences % 2 != 0:
        issues.append("Нечётное число ``` — незакрытый блок кода")

    return issues


# ---------------------------------------------------------------------------
# Translation backends
# ---------------------------------------------------------------------------

class TranslatorBackend:
    """Base class for translation backends."""

    def translate_batch(self, request: TranslationRequest) -> TranslationResult:
        raise NotImplementedError


class AgentBackend(TranslatorBackend):
    """Generates task files for Claude Code agents (current approach)."""

    def __init__(self, tasks_dir: str = "."):
        self.tasks_dir = tasks_dir

    def translate_batch(self, request: TranslationRequest) -> TranslationResult:
        """Generate task files; actual translation happens externally."""
        batch_size = 16
        pages = request.pages
        tasks = []

        for i in range(0, len(pages), batch_size):
            batch = pages[i:i + batch_size]
            page_nums = [p.page_number for p in batch]
            task = {
                "type": "translate",
                "pages": page_nums,
                "chapter": request.chapter,
                "structural_hints": {
                    str(p.page_number): {
                        "has_code": p.has_code,
                        "has_table": p.has_table,
                        "has_figure_ref": p.has_figure_ref,
                        "has_debug_session": p.has_debug_session,
                    }
                    for p in batch
                },
            }
            if request.glossary:
                task["glossary"] = request.glossary.to_prompt()
            if request.manifest_context:
                task["manifest_context"] = request.manifest_context
            tasks.append(task)

        tasks_file = os.path.join(
            self.tasks_dir, f"ch{request.chapter}_tasks.json"
        )
        existing = []
        if os.path.exists(tasks_file):
            with open(tasks_file) as f:
                existing = [t for t in json.load(f) if t["type"] != "translate"]
        with open(tasks_file, "w") as f:
            json.dump(existing + tasks, f, ensure_ascii=False, indent=2)

        return TranslationResult(pages=[], chapter=request.chapter)


class APIBackend(TranslatorBackend):
    """LLM API calls — supports Anthropic, OpenAI, and OpenAI-compatible providers."""

    def __init__(self):
        self.provider = os.environ.get("AI_PROVIDER", "").lower()
        self.api_key = os.environ.get("AI_API_KEY", "")
        self.base_url = os.environ.get("AI_BASE_URL", "")
        self.model = os.environ.get("AI_MODEL", "")

        if not self.api_key:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if self.api_key:
                self.provider = "anthropic"

        if not self.api_key:
            raise ValueError(
                "AI_API_KEY не задан. Установите AI_PROVIDER + AI_API_KEY "
                "(или ANTHROPIC_API_KEY для обратной совместимости)"
            )

        if not self.provider:
            self.provider = "openai"

        if not self.model:
            self.model = _default_model(self.provider)

    def _call_anthropic(self, prompt: str) -> str:
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic")
        client = anthropic.Anthropic(api_key=self.api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _call_openai(self, prompt: str) -> str:
        try:
            import openai
        except ImportError:
            raise ImportError("pip install openai")
        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        client = openai.OpenAI(**kwargs)
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    def _call_llm(self, prompt: str) -> str:
        if self.provider == "anthropic":
            return self._call_anthropic(prompt)
        return self._call_openai(prompt)

    def translate_batch(self, request: TranslationRequest) -> TranslationResult:
        results = []
        glossary = request.glossary
        max_retries = int(os.environ.get("TRANSLATE_MAX_RETRIES", "3"))

        min_interval = float(os.environ.get("TRANSLATE_MIN_INTERVAL", "1.0"))
        last_call = 0.0

        total = len(request.pages)
        for idx, page in enumerate(request.pages, 1):
            log.info("Перевод стр.%s (%d/%d) [%s/%s]",
                     page.page_number, idx, total, self.provider, self.model)
            prompt = self._build_prompt(page, request)
            translated_text = ""

            elapsed = time.time() - last_call
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)

            for attempt in range(max_retries):
                try:
                    translated_text = self._call_llm(prompt)
                    last_call = time.time()
                    break
                except Exception as e:
                    wait = 2 ** attempt
                    log.warning("Стр.%s: ошибка API (%s), повтор через %sс (%s/%s)",
                                page.page_number, e, wait, attempt + 1, max_retries)
                    if attempt < max_retries - 1:
                        time.sleep(wait)
                    else:
                        translated_text = ""

            issues = validate_translation(page, translated_text, glossary, request.target_lang)
            results.append(TranslatedPage(
                page_number=page.page_number,
                text=translated_text,
                issues=issues,
            ))

        return TranslationResult(pages=results, chapter=request.chapter)

    _LANG_NAMES = {
        "ru": "Russian", "en": "English", "de": "German", "fr": "French",
        "es": "Spanish", "it": "Italian", "pt": "Portuguese", "zh": "Chinese",
        "ja": "Japanese", "ko": "Korean", "ar": "Arabic", "hi": "Hindi",
        "uk": "Ukrainian", "pl": "Polish", "cs": "Czech", "tr": "Turkish",
        "nl": "Dutch", "sv": "Swedish", "da": "Danish", "fi": "Finnish",
    }

    def _build_prompt(self, page: PageContent,
                      request: TranslationRequest) -> str:
        lang = request.target_lang
        lang_name = self._LANG_NAMES.get(lang, lang)
        desc = book_profile.book_description or "technical book"

        parts = [f"Translate the following text from the book \"{desc}\" into {lang_name}.\n"]

        if request.glossary:
            parts.append(request.glossary.to_prompt())
            parts.append("")

        hints = []
        if page.has_code:
            hints.append("contains code listing — keep in ``` block")
        if page.has_debug_session:
            hints.append("contains DEBUG session — keep all output in one ``` block")
        if page.has_table:
            hints.append("contains a table — use markdown table")
        if page.has_figure_ref:
            hints.append(f"references Figure {page.has_figure_ref}")
        if hints:
            parts.append("Structural hints: " + "; ".join(hints))
            parts.append("")

        if request.manifest_context:
            parts.append(request.manifest_context)
            parts.append("")

        parts.append("--- TEXT TO TRANSLATE ---")
        parts.append(page.text)

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _default_model(provider: str) -> str:
    defaults = {
        "anthropic": "claude-sonnet-4-20250514",
        "openai": "gpt-4o",
        "google": "gemini-2.5-flash",
    }
    return defaults.get(provider, "gpt-4o")


class TranslatorClient:
    """Main entry point for translations."""

    def __init__(self, backend: TranslatorBackend,
                 glossary: Glossary | None = None):
        self.backend = backend
        self.glossary = glossary

    @classmethod
    def create(cls, mode: str = "agent",
               glossary_path: str = "glossary.json") -> TranslatorClient:
        glossary = Glossary.load(glossary_path)
        if mode == "api":
            backend = APIBackend()
        elif mode == "agent":
            backend = AgentBackend()
        else:
            raise ValueError(f"Неизвестный режим: {mode}")
        return cls(backend=backend, glossary=glossary)

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if self.glossary and not request.glossary:
            request.glossary = self.glossary
        return self.backend.translate_batch(request)

    def validate_existing(self, translations_dir: str, chapter: int,
                          start: int, end: int,
                          source_json: str | None = None) -> TranslationResult:
        """Validate already-completed translations against contracts."""
        all_translations: dict[str, str] = {}
        for fname in sorted(os.listdir(translations_dir)):
            if fname.startswith(f"ch{chapter}") and fname.endswith(".json"):
                with open(os.path.join(translations_dir, fname), encoding="utf-8") as f:
                    all_translations.update(json.load(f))

        source_pages: dict[int, PageContent] = {}
        if source_json and os.path.exists(source_json):
            with open(source_json, encoding="utf-8") as f:
                raw = json.load(f)
            for pg_str, text in raw.items():
                pg = int(pg_str)
                source_pages[pg] = _classify_page(pg, text)

        results = []
        for pg in range(start, end + 1):
            pg_str = str(pg)
            translated = all_translations.get(pg_str, "")
            source = source_pages.get(pg, PageContent(page_number=pg, text=""))
            issues = validate_translation(source, translated, self.glossary, request.target_lang) if translated else ["No translation"]
            results.append(TranslatedPage(
                page_number=pg,
                text=translated,
                issues=issues,
            ))

        return TranslationResult(pages=results, chapter=chapter)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_page(page_num: int, text: str,
                   manifest: dict | None = None) -> PageContent:
    """Analyze raw page text to detect structural elements."""
    has_code = any(book_profile.is_asm_line(line) for line in text.split('\n'))
    has_debug = book_profile.has_debug_session(text)
    has_table = '|' in text and text.count('|') > 6

    fig_match = re.search(r'Figure\s+(\d+\.\d+)', text)
    fig_ref = fig_match.group(1) if fig_match else None

    element_order = None
    if manifest:
        order = manifest.get("element_order", {})
        element_order = order.get(str(page_num))

    return PageContent(
        page_number=page_num,
        text=text,
        has_code=has_code,
        has_table=has_table,
        has_figure_ref=fig_ref,
        has_debug_session=has_debug,
        element_order=element_order,
    )


def _format_manifest(manifest: dict, pages: list[int]) -> str:
    """Format manifest info relevant to pages being translated."""
    lines = []
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
