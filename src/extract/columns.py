def detect_columns(blocks: list[dict]) -> int:
    text_blocks = [b for b in blocks if b["block_type"] == "text"
                   and len(b["text"].strip()) > 30]
    if len(text_blocks) < 4:
        return 1

    page_w = text_blocks[0].get("page_width", 0)
    if not page_w:
        return 1

    narrow = [b for b in text_blocks if (b["x1"] - b["x0"]) < page_w * 0.6]
    if len(narrow) < 4:
        return 1

    tolerance = page_w * 0.05
    x0s = sorted(b["x0"] for b in narrow)
    clusters: list[list[float]] = []
    for x in x0s:
        placed = False
        for cluster in clusters:
            if abs(x - cluster[0]) < tolerance:
                cluster.append(x)
                placed = True
                break
        if not placed:
            clusters.append([x])

    significant = [c for c in clusters if len(c) >= 3]
    if len(significant) >= 2:
        centers = sorted(sum(c) / len(c) for c in significant)
        if len(centers) >= 2 and (centers[1] - centers[0]) > page_w * 0.2:
            return 2

    return 1


def sort_blocks_by_columns(blocks: list[dict], num_columns: int) -> list[dict]:
    if num_columns <= 1:
        return sorted(blocks, key=lambda b: (b["y0"], b["x0"]))

    page_w = blocks[0].get("page_width", 0) if blocks else 0
    mid = page_w / 2 if page_w else 0

    wide = []
    left = []
    right = []
    for b in blocks:
        width = b["x1"] - b["x0"]
        if width > page_w * 0.6:
            wide.append(b)
        elif b["x0"] + width / 2 < mid:
            left.append(b)
        else:
            right.append(b)

    left.sort(key=lambda b: b["y0"])
    right.sort(key=lambda b: b["y0"])
    wide.sort(key=lambda b: b["y0"])

    result = []
    li = ri = wi = 0
    while li < len(left) or ri < len(right) or wi < len(wide):
        next_wide_y = wide[wi]["y0"] if wi < len(wide) else float("inf")

        while li < len(left) and left[li]["y0"] < next_wide_y:
            result.append(left[li])
            li += 1
        while ri < len(right) and right[ri]["y0"] < next_wide_y:
            result.append(right[ri])
            ri += 1
        if wi < len(wide):
            result.append(wide[wi])
            wi += 1

    return result
