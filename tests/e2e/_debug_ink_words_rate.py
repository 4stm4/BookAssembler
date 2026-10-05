"""Debug-only: how many of a fixture table's stacked lines rules._ink_words
cut into as many ink runs as they have words (the rest keep OCR's boxes),
with a few that did not and their counts.

python3 tests/e2e/_debug_ink_words_rate.py <pdf>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

import pymupdf

from src.analyzers.table import rules
from tests.e2e.test_assembled_table_pdf import _extract_table

calls = []
real = rules._ink_words


def traced(page, line):
    out = real(page, line)
    calls.append((line, out != [(w[0], w[2]) for w in line]))
    return out


rules._ink_words = traced
_extract_table(Path(sys.argv[1]))
hit = sum(1 for _, ok in calls if ok)
print(f"{hit} of {len(calls)} lines cut by their ink")
for line, ok in calls:
    if not ok and len(line) > 1:
        print("  kept boxes:", " ".join(w[4] for w in line)[:80])
