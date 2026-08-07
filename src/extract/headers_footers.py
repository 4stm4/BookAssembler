import re
from collections import Counter

_CANDIDATE_PATTERNS = [
    r"^Sec\.\s+\d",
    r"^Chap\.\s+\d",
    r"^Chapter\s+\d",
    r"^Section\s+\d",
    r"^Глава\s+\d",
    r"^Раздел\s+\d",
]


def detect_headers_footers(all_blocks: list[dict],
                           page_count: int) -> tuple[set[str], list[re.Pattern]]:
    if page_count < 3:
        return set(), []

    top_texts: Counter = Counter()
    bottom_texts: Counter = Counter()

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

    hf_patterns = []
    for pat_str in _CANDIDATE_PATTERNS:
        pat = re.compile(pat_str, re.IGNORECASE)
        match_count = sum(1 for t in list(top_texts) + list(bottom_texts)
                          if pat.search(t))
        if match_count >= threshold:
            hf_patterns.append(pat)

    return hf_texts, hf_patterns
