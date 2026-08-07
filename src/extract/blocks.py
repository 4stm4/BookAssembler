def extract_page_blocks(page) -> list[dict]:
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
