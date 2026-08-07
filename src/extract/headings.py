import re
from collections import Counter


def detect_body_font_size(all_blocks: list[dict]) -> float:
    size_counts: Counter = Counter()
    for b in all_blocks:
        if b["block_type"] != "text":
            continue
        char_count = len(b["text"].strip())
        size_counts[round(b["font_size"])] += char_count
    if not size_counts:
        return 0
    return size_counts.most_common(1)[0][0]


def build_heading_hierarchy(all_blocks: list[dict],
                            body_size: float) -> dict[int, int]:
    if not body_size:
        return {}

    heading_sizes: Counter = Counter()
    for b in all_blocks:
        if b["block_type"] != "text":
            continue
        size = round(b["font_size"])
        if size > body_size * 1.1:
            heading_sizes[size] += 1

    if not heading_sizes:
        return {}

    sorted_sizes = sorted(heading_sizes.keys(), reverse=True)
    levels = {}
    for i, size in enumerate(sorted_sizes):
        levels[size] = min(i + 1, 6)

    return levels


def classify_block(block: dict, body_size: float,
                   heading_levels: dict[int, int]) -> str:
    text = block["text"].strip()

    if re.match(r"^\d{1,4}$", text):
        return "page_number"

    if block["is_mono"]:
        return "code"

    if body_size > 0:
        rounded = round(block["font_size"])
        if rounded in heading_levels:
            return f"heading_{heading_levels[rounded]}"

    if re.match(
        r"^(Figure|Fig\.|Table|Example|FIGURE|TABLE|EXAMPLE|"
        r"Рис\.|Рисунок|Таблица|Пример)\s+\d",
        text, re.IGNORECASE,
    ):
        return "caption"

    return "body"
