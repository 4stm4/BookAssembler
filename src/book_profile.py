"""
Book profile — all book-specific constants in one place.

Loaded from book_profile.yaml if present, otherwise uses built-in defaults.
Every module that needs book-specific data imports from here instead of
hardcoding values.
"""

import os
import re

_SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)


class BookProfile:
    """Holds all book-specific configuration."""

    def __init__(
        self,
        *,
        asm_mnemonics: set[str] | None = None,
        debug_indicators: list[str] | None = None,
        debug_line_patterns: list[str] | None = None,
        debug_flag_strings: list[str] | None = None,
        section_pattern: str = "",
        section_flags: int = 0,
        table_indicators: list[tuple[str, str]] | None = None,
        figure_categories: dict[str, list[str]] | None = None,
        subscript_bases: list[int] | None = None,
        book_description: str = "",
        translation_prompt_intro: str = "",
    ):
        self.asm_mnemonics = asm_mnemonics or set()
        self.debug_indicators = debug_indicators or []
        self.debug_line_patterns = debug_line_patterns or []
        self.debug_flag_strings = debug_flag_strings or []
        self.section_pattern = section_pattern
        self.section_flags = section_flags
        self.table_indicators = table_indicators or []
        self.figure_categories = figure_categories or {}
        self.subscript_bases = subscript_bases or []
        self.book_description = book_description
        self.translation_prompt_intro = translation_prompt_intro

        self._compiled_section_re = (
            re.compile(section_pattern, section_flags) if section_pattern else None
        )
        self._compiled_debug_line_res = [
            re.compile(p) for p in self.debug_line_patterns
        ]

    def is_asm_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        first_word = stripped.split()[0].upper().rstrip(",;:")
        return first_word in self.asm_mnemonics

    def has_debug_session(self, text: str) -> bool:
        return any(d in text for d in self.debug_indicators)

    def is_debug_line(self, line: str) -> bool:
        stripped = line.strip()
        if any(d in stripped for d in self.debug_indicators):
            return True
        if stripped in self.debug_flag_strings:
            return True
        if self.is_asm_line(stripped):
            return True
        return any(r.match(stripped) for r in self._compiled_debug_line_res)

    def find_sections(self, text: str):
        if not self._compiled_section_re:
            return []
        return self._compiled_section_re.finditer(text)

    def classify_figure(self, caption: str) -> str:
        cap = caption.lower()
        for category, keywords in self.figure_categories.items():
            if any(kw in cap for kw in keywords):
                return category
        return "general_diagram"

    def fix_subscripts(self, text: str) -> str:
        for base in self.subscript_bases:
            digits_str = str(base)
            subscript = digits_str.translate(_SUBSCRIPT_DIGITS)
            text = re.sub(rf'(?<!\w)_{base}\b', subscript, text)
        return text

    def get_table_indicator_patterns(self) -> list[tuple[str, str]]:
        return self.table_indicators


# ---------------------------------------------------------------------------
# Built-in profile for "The 8088 and 8086 Microprocessors"
# ---------------------------------------------------------------------------

_X86_MNEMONICS = {
    "MOV", "ADD", "SUB", "MUL", "DIV", "INC", "DEC", "AND", "OR",
    "XOR", "NOT", "NEG", "PUSH", "POP", "XCHG", "LEA", "LDS", "LES",
    "CMP", "TEST", "JMP", "CALL", "RET", "INT", "SHL", "SHR", "SAL",
    "SAR", "ROL", "ROR", "RCL", "RCR", "ADC", "SBB", "IMUL", "IDIV",
    "CBW", "CWD", "XLAT", "LAHF", "SAHF", "DAA", "DAS", "AAA", "AAS",
    "AAM", "AAD", "LODSB", "LODSW", "STOSB", "STOSW", "MOVSB", "MOVSW",
    "NOP", "HLT",
}

_X86_PROFILE = BookProfile(
    asm_mnemonics=_X86_MNEMONICS,
    debug_indicators=["C:\\DOS>DEBUG", "C>DEBUG", "C:\\>DEBUG"],
    debug_line_patterns=[
        r"^-",
        r"^\u2014",
        r"^[A-Z]{2}=",
        r"^[0-9A-F]{4}:",
        r"^[A-Z]{2}\s+[0-9A-F]{4}",
        r"^C:\\DOS>",
        r"^C:\\>",
        r"^:",
    ],
    debug_flag_strings=[
        "", "NV UP EI PL NZ NA PO NC", "OV UP EI PL NZ NA PO NC",
    ],
    section_pattern=r"▲?\s*(\d+\.\d+)\s+([A-Z][A-Z\s/]+(?:INSTRUCTIONS?|SET|OPERATIONS?))",
    section_flags=0,
    table_indicators=[
        (r"Mnemonic\s+Meaning\s+Format", "instruction_summary"),
        (r"Мнемоника\s+Значение\s+Формат", "instruction_summary"),
        (r"Destination\s+Source", "operand_table"),
        (r"Назначение\s+Источник", "operand_table"),
        (r"Flags\s+affected", "flags_table"),
        (r"Затронутые\s+флаги", "flags_table"),
    ],
    figure_categories={
        "debug_session": ["display sequence", "debug"],
        "source_listing": ["source program", "source listing", "source\nprogram"],
        "block_diagram": ["block diagram", "architecture", "bus", "system"],
        "results_table": ["result"],
        "instruction_diagram": ["shift", "rotate", "logic", "arithmetic"],
        "data_flow": ["exchange", "transfer", "move"],
        "continuation": ["continued"],
        "register_diagram": ["instruction"],
    },
    subscript_bases=[2, 8, 10, 16, 32, 64],
    book_description="техническая книга по микропроцессорам 8088/8086",
    translation_prompt_intro=(
        "Переведи следующий текст из технической книги по микропроцессорам "
        "8088/8086 на русский язык.\n"
    ),
)


def _load_profile(path: str = "book_profile.yaml") -> BookProfile:
    """Load book profile from YAML, fall back to built-in x86 profile."""
    config_path = os.path.join(PROJECT_ROOT, path)
    if not os.path.exists(config_path):
        return _X86_PROFILE
    try:
        import yaml
    except ImportError:
        return _X86_PROFILE

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    return BookProfile(
        asm_mnemonics=set(cfg.get("asm_mnemonics", [])),
        debug_indicators=cfg.get("debug_indicators", []),
        debug_line_patterns=cfg.get("debug_line_patterns", []),
        debug_flag_strings=cfg.get("debug_flag_strings", []),
        section_pattern=cfg.get("section_pattern", ""),
        section_flags=cfg.get("section_flags", 0),
        table_indicators=[
            (p["pattern"], p["type"])
            for p in cfg.get("table_indicators", [])
        ],
        figure_categories=cfg.get("figure_categories", {}),
        subscript_bases=cfg.get("subscript_bases", [2, 10, 16]),
        book_description=cfg.get("book_description", ""),
        translation_prompt_intro=cfg.get("translation_prompt_intro", ""),
    )


profile = _load_profile()
