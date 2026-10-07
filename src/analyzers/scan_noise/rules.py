"""scan_noise: Pure decision logic — no KRM writes, no I/O."""

from collections import Counter
from typing import List, Tuple

from src.analyzers.scan_noise.signals import (
    MAX_DOMINANT_LETTER_SHARE,
    MIN_ADVANCE_EM,
    MIN_LETTERS,
    OPERATORS,
    _BROKEN_TOKEN_RE,
    _CYRILLIC_VOWELS,
    _JUDGEABLE_RE,
    _LATIN_VOWELS,
    _LEADER_RE,
    _REPEAT_RE,
    _WORD_RE,
)


def is_real_word(word: str) -> bool:
    """A letter run that reads as a word rather than scanner debris."""
    if not _JUDGEABLE_RE.match(word):
        return True  # a script we cannot judge — never call it debris
    low = word.lower()
    if not any(c in _LATIN_VOWELS or c in _CYRILLIC_VOWELS for c in low):
        return False
    dominant = Counter(low).most_common(1)[0][1]
    return dominant / len(low) <= MAX_DOMINANT_LETTER_SHARE


def is_scan_noise(text: str) -> bool:
    """Letter debris from a non-text region of a scan.

    Only text that has letters can be letter debris: a row of numbers, a
    date or a price is content, not noise. Among the rest, noise is text
    whose punctuation outweighs its letters - a formula's operators and
    brackets are none - or whose letters form no real word and show debris
    in their tokens. A mnemonic has no real word but clean tokens ("LD r,
    (IX+d)").
    """
    core = _LEADER_RE.sub(" ", text or "")
    chars = [c for c in core if not c.isspace()]
    letters = sum(c.isalpha() for c in chars)
    if letters < MIN_LETTERS:
        return False
    symbols = sum(not c.isalnum() and c not in OPERATORS for c in chars)
    if symbols > letters:
        return True
    if any(is_real_word(w) for w in _WORD_RE.findall(core)):
        return False
    return any(_REPEAT_RE.search(t) or _BROKEN_TOKEN_RE.search(t) for t in core.split())


def is_squeezed(lines: List[Tuple[str, float, float]]) -> bool:
    """Debris by its boxes: lines - (text, width, height), in points -
    most of which are boxed narrower than their characters could print
    (MIN_ADVANCE_EM)."""
    judged = [(len(t.strip()), w, h) for t, w, h in lines if len(t.strip()) >= 2 and h > 0]
    squeezed = sum(1 for n, w, h in judged if w < MIN_ADVANCE_EM * h * n)
    return bool(judged) and 2 * squeezed > len(judged)
