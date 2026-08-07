from collections import Counter


def detect_table(blocks: list[dict], start_idx: int) -> list[dict] | None:
    if start_idx >= len(blocks):
        return None

    candidates = blocks[start_idx:]
    if len(candidates) < 4:
        return None

    page_h = candidates[0].get("page_height", 0)
    if not page_h:
        return None

    aligned_blocks = []

    for b in candidates:
        if b["block_type"] != "text":
            break
        text = b["text"].strip()
        if not text:
            continue
        lines = text.split("\n")
        if any(len(line) > 80 for line in lines):
            break
        aligned_blocks.append(b)

    if len(aligned_blocks) < 4:
        return None

    tolerance = 20
    x0_values = [round(b["x0"]) for b in aligned_blocks]
    x0_clusters: Counter = Counter()
    for x in x0_values:
        rounded = round(x / tolerance) * tolerance
        x0_clusters[rounded] += 1

    col_count = sum(1 for c in x0_clusters.values() if c >= 2)
    if col_count >= 2:
        return aligned_blocks

    return None


def blocks_to_markdown_table(blocks: list[dict]) -> str:
    if not blocks:
        return ""

    tolerance = 20

    rows: list[list[dict]] = []
    current_row: list[dict] = [blocks[0]]
    for b in blocks[1:]:
        if abs(b["y0"] - current_row[0]["y0"]) < tolerance:
            current_row.append(b)
        else:
            rows.append(sorted(current_row, key=lambda x: x["x0"]))
            current_row = [b]
    rows.append(sorted(current_row, key=lambda x: x["x0"]))

    if len(rows) < 2:
        return ""

    num_cols = max(len(row) for row in rows)

    lines = []
    for i, row in enumerate(rows):
        cells = [b["text"].strip().replace("\n", " ").replace("|", "\\|")
                 for b in row]
        while len(cells) < num_cols:
            cells.append("")
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in range(num_cols)) + " |")

    return "\n".join(lines)
