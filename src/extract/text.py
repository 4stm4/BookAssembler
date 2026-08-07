import re

from .columns import detect_columns, sort_blocks_by_columns
from .headings import classify_block
from .tables import detect_table, blocks_to_markdown_table
from .lang import get_continuation_pattern

LIST_BULLET_RE = re.compile(
    r"^(?:[•‣◦⁃∙•·\-\*]"
    r"|[a-z]\)"
    r"|\d{1,3}[\.\)]"
    r")\s+",
    re.IGNORECASE,
)

FOOTNOTE_DEF_RE = re.compile(r"^(\d+)\s+(.+)", re.MULTILINE)

XREF_RE = re.compile(
    r"((?:Figure|Fig\.|Table|Example|Рис\.|Рисунок|Таблица|Пример)"
    r"\s+(\d+[\-\.]\d+|\d+))",
    re.IGNORECASE,
)

_DEFAULT_CONTINUATION_RE = get_continuation_pattern("en")


def detect_list_item(text: str) -> tuple[str, str] | None:
    m = LIST_BULLET_RE.match(text)
    if m:
        return m.group().strip(), text[m.end():]
    return None


def add_cross_references(text: str) -> str:
    def _repl(m):
        full = m.group(1)
        anchor = re.sub(r"[^a-z0-9]+", "-", full.lower()).strip("-")
        return f"[{full}](#{anchor})"
    return XREF_RE.sub(_repl, text)


def join_lines(raw: str, continuation_re: re.Pattern | None) -> str:
    sections = re.split(r"(```.*?```)", raw, flags=re.DOTALL)
    result_parts = []

    for section in sections:
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
                   and not line.strip().startswith("#")
                   and not line.strip().startswith("**")
                   and not line.strip().startswith("- ")
                   and not line.strip().startswith("1. ")
                   and not line.strip().startswith("|")
                   and not line.strip().startswith("[^")
                   and lines[j + 1].strip()
                   and not lines[j + 1].strip().startswith("#")
                   and not lines[j + 1].strip().startswith("**")
                   and not lines[j + 1].strip().startswith("- ")
                   and not lines[j + 1].strip().startswith("1. ")
                   and not lines[j + 1].strip().startswith("|")
                   and not lines[j + 1].strip().startswith("![")
                   and not lines[j + 1].strip().startswith("[^")
                   and (re.match(r"^[a-zа-яё,;(]", lines[j + 1].strip())
                        or re.search(r"[,;]\s*$", line.rstrip())
                        or (continuation_re
                            and continuation_re.search(line.rstrip())))):
                next_line = lines[j + 1].strip()
                line = line.rstrip() + " " + next_line
                j += 1
            merged.append(line)
            j += 1
        result_parts.append("\n".join(merged))

    return "".join(result_parts)


def build_page_text(blocks: list[dict], body_size: float,
                    heading_levels: dict[int, int],
                    hf_texts: set[str],
                    hf_patterns: list[re.Pattern] | None = None) -> str:
    num_cols = detect_columns(blocks)
    blocks = sort_blocks_by_columns(blocks, num_cols)

    toc_entries = None
    for b in blocks:
        if "_toc_entries" in b:
            toc_entries = b["_toc_entries"]
            break

    parts: list[str] = []

    if toc_entries:
        for level, title in toc_entries:
            hashes = "#" * min(level, 6)
            parts.append(f"\n{hashes} {title}\n")

    prev_was_image = False
    skip_table_blocks: set[int] = set()
    i = 0

    while i < len(blocks):
        b = blocks[i]
        block_id = id(b)

        if block_id in skip_table_blocks:
            i += 1
            continue

        if b["block_type"] == "image":
            img_file = b.get("image_file")
            if img_file:
                parts.append(f"\n![image]({img_file})\n")
                prev_was_image = True
            i += 1
            continue

        text = b["text"].strip()
        if not text:
            i += 1
            continue

        if text in hf_texts:
            i += 1
            continue

        page_h = b.get("page_height", 0)
        if page_h:
            rel_y = b["y0"] / page_h
            in_margin = rel_y < 0.10 or rel_y > 0.90
            if in_margin:
                if hf_patterns and any(p.search(text) for p in hf_patterns):
                    i += 1
                    continue
                if re.match(r"^\d{1,4}$", text):
                    i += 1
                    continue
                if len(text) < 80 and re.search(
                        r"(Sec\.|Chap\.|Chapter|Section|Глава|Раздел)\s*\d",
                        text, re.IGNORECASE):
                    i += 1
                    continue

        btype = classify_block(b, body_size, heading_levels)

        if btype == "page_number":
            i += 1
            continue

        if btype == "caption" and prev_was_image:
            anchor = re.sub(r"[^a-z0-9]+", "-", text.split("\n")[0].lower()).strip("-")
            parts.append(f'\n**{text}** {{#{anchor}}}\n')
            prev_was_image = False
            i += 1
            continue

        if btype == "caption":
            anchor = re.sub(r"[^a-z0-9]+", "-", text.split("\n")[0].lower()).strip("-")
            parts.append(f'\n**{text}** {{#{anchor}}}\n')
            i += 1
            continue

        prev_was_image = False

        if btype.startswith("heading_"):
            level = int(btype.split("_")[1])
            hashes = "#" * level
            parts.append(f"\n{hashes} {text}\n")
            i += 1
            continue

        if btype == "code":
            parts.append(f"\n```\n{text}\n```\n")
            i += 1
            continue

        table_blocks = detect_table(blocks, i)
        if table_blocks:
            md_table = blocks_to_markdown_table(table_blocks)
            if md_table:
                parts.append(f"\n{md_table}\n")
                for tb in table_blocks:
                    skip_table_blocks.add(id(tb))
                i += len(table_blocks)
                continue

        list_item = detect_list_item(text)
        if list_item:
            marker, content = list_item
            if re.match(r"\d+[\.\)]", marker):
                parts.append(f"1. {content}")
            else:
                parts.append(f"- {content}")
            i += 1
            continue

        if page_h and b["y0"] / page_h > 0.85:
            fn_match = FOOTNOTE_DEF_RE.match(text)
            if fn_match:
                fn_num = fn_match.group(1)
                fn_text = fn_match.group(2)
                parts.append(f"\n[^{fn_num}]: {fn_text}\n")
                i += 1
                continue

        parts.append(text)
        i += 1

    raw = "\n".join(parts)
    raw = re.sub(r"(\w)-\n(\w)", r"\1\2", raw)
    raw = re.sub(r"\n([,;:])", r" \1", raw)
    raw = add_cross_references(raw)
    raw = join_lines(raw, _DEFAULT_CONTINUATION_RE)
    raw = re.sub(r"\n{3,}", "\n\n", raw)

    return raw.strip()
