"""Debug-only: where the overlay's shared text lines are found on the
source page - each strong line (6+ characters) with all its hits - so a
hit outside the table shows up.

python3 tests/e2e/_debug_source_hits.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf, _table_lines

pdf = Path(sys.argv[1])
table = _extract_table(pdf)
bb = table.visual_layout.bounding_box
src = fitz.open(pdf)[0]
print("table box y", round(bb.y0 * src.rect.height, 1), round(bb.y1 * src.rect.height, 1),
      "x", round(bb.x0 * src.rect.width, 1), round(bb.x1 * src.rect.width, 1))
with tempfile.TemporaryDirectory() as td:
    out = fitz.open(_build_single_table_pdf(table, td, "hits"))[1]
    for t in dict.fromkeys(_table_lines(table)):
        s_hits, o_hits = src.search_for(t), out.search_for(t)
        if len(t) >= 6 and s_hits and o_hits:
            print(f"{len(s_hits)}x  {t[:40]!r:44} " + " ".join(f"{h.x0:.0f},{h.y0:.0f}" for h in s_hits[:4]))
