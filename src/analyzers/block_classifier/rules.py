"""block_classifier: Pure decision logic — no KRM writes, no I/O."""

from src.analyzers.access import block_text as _get_text


def _classify_paragraph_confidence(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.10

    length = len(stripped)
    words = stripped.split()
    word_count = len(words)
    alpha_ratio = sum(c.isalpha() for c in stripped) / length if length else 0
    has_period = "." in stripped
    has_sentence = has_period and word_count > 3

    score = 0.50

    if has_sentence and length > 80:
        score += 0.30
    elif has_sentence:
        score += 0.20
    elif length > 50:
        score += 0.10

    if word_count >= 5:
        score += 0.05
    elif word_count == 1:
        score -= 0.15

    if alpha_ratio > 0.6:
        score += 0.05
    elif alpha_ratio < 0.3:
        score -= 0.10

    if length < 5:
        score -= 0.15

    return max(0.10, min(0.95, score))
