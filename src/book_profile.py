"""
Book profile — all book-specific constants in one place.

Loaded from book_profile.yaml if present, otherwise auto-detected from
the book's text content. Every module that needs book-specific data
imports `profile` from here instead of hardcoding values.
"""

import json
import logging
import os
import re

log = logging.getLogger("bookassembler")

_SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
PROJECT_DIR = os.environ.get("BOOKASSEMBLER_PROJECT_DIR",
                             os.path.join(PROJECT_ROOT, "project"))


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
# Known assembly instruction sets for auto-detection
# ---------------------------------------------------------------------------

_KNOWN_ASM = {
    "x86": {
        "MOV", "ADD", "SUB", "MUL", "DIV", "INC", "DEC", "AND", "OR",
        "XOR", "NOT", "NEG", "PUSH", "POP", "XCHG", "LEA", "LDS", "LES",
        "CMP", "TEST", "JMP", "CALL", "RET", "INT", "SHL", "SHR", "SAL",
        "SAR", "ROL", "ROR", "RCL", "RCR", "ADC", "SBB", "IMUL", "IDIV",
        "CBW", "CWD", "XLAT", "LAHF", "SAHF", "DAA", "DAS", "AAA", "AAS",
        "AAM", "AAD", "LODSB", "LODSW", "STOSB", "STOSW", "MOVSB", "MOVSW",
        "NOP", "HLT",
    },
    "arm": {
        "LDR", "STR", "MOV", "ADD", "SUB", "MUL", "AND", "ORR", "EOR",
        "CMP", "BEQ", "BNE", "BL", "BX", "PUSH", "POP", "LDM", "STM",
        "SWI", "NOP",
    },
    "mips": {
        "ADD", "ADDI", "SUB", "AND", "ANDI", "OR", "ORI", "NOR", "SLT",
        "LW", "SW", "BEQ", "BNE", "J", "JAL", "JR", "SLL", "SRL",
        "LUI", "MFHI", "MFLO", "MULT", "DIV", "SYSCALL", "NOP",
    },
}

_KNOWN_DEBUG = {
    "dos_debug": {
        "indicators": ["C:\\DOS>DEBUG", "C>DEBUG", "C:\\>DEBUG"],
        "line_patterns": [
            r"^-", r"^\u2014", r"^[A-Z]{2}=", r"^[0-9A-F]{4}:",
            r"^[A-Z]{2}\s+[0-9A-F]{4}", r"^C:\\DOS>", r"^C:\\>", r"^:",
        ],
        "flag_strings": ["", "NV UP EI PL NZ NA PO NC", "OV UP EI PL NZ NA PO NC"],
    },
}

# Section heading patterns to try, in priority order
_SECTION_PATTERNS = [
    # "1-1 Title" or "1-1-1 Title" (dash-separated)
    (r"^\s*(\d+-\d+(?:-\d+)?)\s+([A-Z][A-Za-z\s,/]+)", re.MULTILINE),
    # "1.1 TITLE IN UPPERCASE"
    (r"▲?\s*(\d+\.\d+)\s+([A-Z][A-Z\s/]+(?:INSTRUCTIONS?|SET|OPERATIONS?))", 0),
    # "1.1 Title In Title Case"
    (r"^\s*(\d+\.\d+)\s+([A-Z][A-Za-z\s,/]+)", re.MULTILINE),
    # "Section 1.1 Title"
    (r"^\s*Section\s+(\d+\.\d+)\s+(.+)", re.MULTILINE | re.IGNORECASE),
]

# Figure caption patterns to try
_FIGURE_PATTERNS = [
    r"Figure\s+(\d+[-.]\d+)",
    r"Fig\.\s*(\d+[-.]\d+)",
    r"FIGURE\s+(\d+[-.]\d+)",
]

# Example patterns to try
_EXAMPLE_PATTERNS = [
    r"EXAMPLE\s+(\d+[-.]\d+)",
    r"Example\s+(\d+[-.]\d+)",
]

# Table header patterns to detect
_TABLE_HEADER_CANDIDATES = [
    (r"Mnemonic\s+Meaning\s+Format", "instruction_summary"),
    (r"Destination\s+Source", "operand_table"),
    (r"Flags?\s+affected", "flags_table"),
    (r"Register\s+Function", "register_table"),
    (r"Address\s+Data", "memory_table"),
    (r"Signal\s+Function", "signal_table"),
    (r"Pin\s+Name", "pin_table"),
    (r"Bit\s+Name", "bit_table"),
    (r"Instruction\s+Description", "instruction_table"),
    (r"Opcode\s+Mnemonic", "opcode_table"),
    (r"Name\s+Description", "description_table"),
    (r"Parameter\s+Value", "parameter_table"),
    (r"Symbol\s+Meaning", "symbol_table"),
]

# Generic figure keywords for classification
_DEFAULT_FIGURE_CATEGORIES = {
    "block_diagram": ["block diagram", "architecture", "bus", "system", "organization"],
    "timing_diagram": ["timing", "waveform", "clock"],
    "circuit_diagram": ["circuit", "schematic", "logic"],
    "flowchart": ["flowchart", "flow chart", "algorithm"],
    "data_flow": ["data flow", "transfer", "exchange", "move"],
    "memory_map": ["memory map", "address map", "memory layout"],
    "register_diagram": ["register", "flag"],
    "pin_diagram": ["pin", "pinout", "package"],
    "instruction_diagram": ["instruction", "opcode", "format"],
    "debug_session": ["debug", "display sequence"],
    "source_listing": ["source program", "source listing", "source code", "program listing"],
    "results_table": ["result", "output"],
    "continuation": ["continued", "cont."],
}


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

def detect_profile(texts: dict[str, str], book_title: str = "") -> BookProfile:
    """Auto-detect book profile from extracted text pages.

    Args:
        texts: {page_number_str: page_text} from extract stage
        book_title: from chapters.yaml
    """
    all_text = "\n".join(texts.values())

    # 1. Detect assembly instruction set
    # Only match mnemonics that look like actual instructions (mnemonic + operand)
    asm_mnemonics = set()
    detected_asm_type = ""
    best_hits = 0
    best_name = ""
    best_set = set()
    for name, mnemonics in _KNOWN_ASM.items():
        hits = 0
        for m in mnemonics:
            pattern = rf'^\s*{m}[ \t]+\S'
            hits += len(re.findall(pattern, all_text, re.MULTILINE))
        if hits > best_hits:
            best_hits = hits
            best_name = name
            best_set = mnemonics
    if best_hits >= 10:
        asm_mnemonics = best_set
        detected_asm_type = best_name
        log.info("Обнаружен ассемблер: %s (%d совпадений)", best_name, best_hits)

    # 2. Detect debug session indicators
    debug_indicators = []
    debug_line_patterns = []
    debug_flag_strings = []
    for name, cfg in _KNOWN_DEBUG.items():
        if any(ind in all_text for ind in cfg["indicators"]):
            debug_indicators = cfg["indicators"]
            debug_line_patterns = cfg["line_patterns"]
            debug_flag_strings = cfg["flag_strings"]
            log.info("Обнаружены DEBUG-сессии: %s", name)
            break

    # 3. Detect section heading format
    section_pattern = ""
    section_flags = 0
    for pattern, flags in _SECTION_PATTERNS:
        matches = re.findall(pattern, all_text, flags)
        if len(matches) >= 3:
            section_pattern = pattern
            section_flags = flags
            log.info("Обнаружен формат секций: %s (%d совпадений)", pattern[:50], len(matches))
            break

    # 4. Detect figure numbering
    figure_pattern_used = ""
    for fp in _FIGURE_PATTERNS:
        matches = re.findall(fp, all_text)
        if len(matches) >= 2:
            figure_pattern_used = fp
            log.info("Обнаружены фигуры: %s (%d)", fp, len(matches))
            break

    # 5. Detect table header patterns
    table_indicators = []
    for pattern, ttype in _TABLE_HEADER_CANDIDATES:
        if re.search(pattern, all_text, re.IGNORECASE):
            table_indicators.append((pattern, ttype))
            log.info("Обнаружена таблица: %s", ttype)

    # 6. Detect subscript bases
    subscript_bases = []
    for base in [2, 8, 10, 16, 32, 64]:
        if re.search(rf'(?<!\w)_{base}\b', all_text):
            subscript_bases.append(base)
    if not subscript_bases:
        subscript_bases = [2, 10, 16]

    # 7. Figure categories — use defaults, they're generic enough
    figure_categories = _DEFAULT_FIGURE_CATEGORIES

    # 8. Build description and prompt intro from book title
    desc = book_title if book_title else "техническая книга"
    prompt_intro = ""

    detected = BookProfile(
        asm_mnemonics=asm_mnemonics,
        debug_indicators=debug_indicators,
        debug_line_patterns=debug_line_patterns,
        debug_flag_strings=debug_flag_strings,
        section_pattern=section_pattern,
        section_flags=section_flags,
        table_indicators=table_indicators,
        figure_categories=figure_categories,
        subscript_bases=subscript_bases,
        book_description=desc,
        translation_prompt_intro=prompt_intro,
    )

    log.info("Профиль книги определён автоматически")
    return detected


def save_profile(bp: BookProfile, path: str = "book_profile.yaml"):
    """Save detected profile to YAML for review and editing."""
    try:
        import yaml
    except ImportError:
        log.warning("pyyaml не установлен — профиль не сохранён")
        return

    data = {
        "book_description": bp.book_description,
        "translation_prompt_intro": bp.translation_prompt_intro,
        "asm_mnemonics": sorted(bp.asm_mnemonics),
        "debug_indicators": bp.debug_indicators,
        "debug_line_patterns": bp.debug_line_patterns,
        "debug_flag_strings": bp.debug_flag_strings,
        "section_pattern": bp.section_pattern,
        "section_flags": int(bp.section_flags),
        "table_indicators": [
            {"pattern": p, "type": t} for p, t in bp.table_indicators
        ],
        "figure_categories": bp.figure_categories,
        "subscript_bases": bp.subscript_bases,
    }

    out = os.path.join(PROJECT_DIR, path)
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.info("Профиль сохранён: %s", path)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _load_profile(path: str = "book_profile.yaml") -> BookProfile:
    """Load book profile from YAML. Returns None if file doesn't exist."""
    config_path = os.path.join(PROJECT_DIR, path)
    if not os.path.exists(config_path):
        return None
    try:
        import yaml
    except ImportError:
        return None

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


def load_or_detect_profile() -> BookProfile:
    """Load from YAML if exists, otherwise return empty profile (detect later)."""
    loaded = _load_profile()
    if loaded:
        return loaded
    return BookProfile()


def reload_profile():
    """Reload profile from YAML after auto-detection saved it."""
    global profile
    loaded = _load_profile()
    if loaded:
        profile = loaded


profile = load_or_detect_profile()
