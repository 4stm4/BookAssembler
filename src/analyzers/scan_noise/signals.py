"""scan_noise: what marks letter debris from a scan — no KRM access.

A scanned logo, crest or smudge comes through the text layer as a run of
punctuation and stray letters: ", 1IIIIiK,8I ,..i!C\"'-". These are the
attributes that tell it apart from real text. The rule that applies them
lives in rules.py.
"""

import re

# Runs of leader characters — the dots between a contents entry and its page
# number, dense ("......") or spaced (". . . .", ".  .  ."). They are layout,
# not text: counted as punctuation they made every contents line look like
# debris, and the adapter used to drop them all.
_LEADER_RE = re.compile(r"(?:[.·…_]\s*){3,}")

# A run of letters in any script — Cyrillic included. The adapter's old check
# only knew [A-Za-z], so every Russian paragraph without a Latin word in it
# was judged to hold no real word and was discarded.
_WORD_RE = re.compile(r"[^\W\d_]{3,}")

# Vowels of the scripts a word can be judged in. A word in any other script
# (Greek, CJK, Latin with diacritics from a broken font encoding) is not
# judged at all: tombstoning a page of text we cannot read is worse than
# keeping a smudge.
_LATIN_VOWELS = frozenset("aeiouy")
_CYRILLIC_VOWELS = frozenset("аеёиоуыэюяіїєў")
_JUDGEABLE_RE = re.compile(r"^(?:[A-Za-z]+|[Ѐ-ӿ]+)$")

# Too little to judge: a part number ("UM008011-0816"), a folio, a
# unit. Debris is recognised by what its letters fail to form; with fewer
# letters than this there is nothing to go on.
MIN_LETTERS = 3

# A real word is not one letter repeated: OCR of a vertical bar or a crest
# edge reads as "IIIIiK". Measured on the Intel Series 3000 cover; real words
# in the test books peak at 0.5 ("Sussex", "Mississippi" 0.36).
MAX_DOMINANT_LETTER_SHARE = 0.6
