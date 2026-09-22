"""Debug-only: dump the assembled grid's rows around the 'Quiescent
Current' section for FIXTURE_B. Run with python3, not pytest."""
import sys

sys.path.insert(0, "/app")

from tests.e2e.test_assembled_table_pdf import FIXTURE_B, _extract_table

table = _extract_table(FIXTURE_B)
for i, row in enumerate(table.grid):
    cells = []
    for cell in row:
        t = " ".join(
            s.text.strip() for c in cell.content for il in c.inlines for s in il.spans
        )
        cells.append(t)
    print(i, cells)
