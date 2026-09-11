"""scan_noise: Pure decision logic — no KRM writes, no I/O."""

from collections import Counter

from src.analyzers.scan_noise.signals import (
    MAX_DOMINANT_LETTER_SHARE,
    MIN_LETTERS,
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
    whose punctuation outweighs its letters — or whose letters form no real
    word and show debris in their tokens. A mnemonic has no real word but
    clean tokens ("LD r, (IX+d)").
    """
    core = _LEADER_RE.sub(" ", text or "")
    chars = [c for c in core if not c.isspace()]
    letters = sum(c.isalpha() for c in chars)
    if letters < MIN_LETTERS:
        return False
    digits = sum(c.isdigit() for c in chars)
    symbols = len(chars) - letters - digits
    if symbols > letters:
        return True
    if any(is_real_word(w) for w in _WORD_RE.findall(core)):
        return False
    return any(_REPEAT_RE.search(t) or _BROKEN_TOKEN_RE.search(t) for t in core.split())
