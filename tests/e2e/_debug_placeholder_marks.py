"""Debug-only: the placeholder marks _find_placeholder_marks read off a
table fixture, each with its row's cells - and which rows were taken for
leaders.

python3 tests/e2e/_debug_placeholder_marks.py <pdf>
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")
from src.analyzers.table.rules import _cell_text_of
from tests.e2e.test_assembled_table_pdf import _extract_table

t = _extract_table(Path(sys.argv[1]))
for m in (t.metadata or {}).get("placeholder_marks", []):
    row = t.grid[m["row"]]
    b = m["bbox"]
    print(f"mark row {m['row']} x {b[0] * 595:.1f}-{b[2] * 595:.1f} y {b[1] * 842:.1f}  | "
          + " | ".join(f"{_cell_text_of(c)!r}{'*' if (c.metadata or {}).get('leader_after') else ''}" for c in row))
