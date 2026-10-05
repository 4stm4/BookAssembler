"""Debug-only: the table of contents the pipeline reads off a fixture -
its containers and their entries (number, title, page, level, source page,
description).

python3 tests/e2e/_debug_toc_entries.py <pdf>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from tests.e2e.test_toc_overlay import _extract_tocs

for toc in _extract_tocs(Path(sys.argv[1])):
    print(f"toc {toc.title!r} page {toc.visual_layout.page_or_screen_index if toc.visual_layout else None}")
    for e in toc.children:
        if getattr(e, "is_tombstoned", False):
            continue
        vl = e.visual_layout
        print(f"  p{vl.page_or_screen_index if vl else '?'} L{getattr(e, 'level', None)} "
              f"{getattr(e, 'chapter_number', None)!r:8} {getattr(e, 'entry_text', '')[:40]!r:44} "
              f"{getattr(e, 'page_label', None)!r:6} {(e.metadata or {}).get('toc_description', '')[:30]!r}")
