"""Debug-only: dump the assembled grid for FIXTURE_A to check for
content loss/corruption, mirroring _debug_grid_dump_b.py. Run with
python3, not pytest."""
import sys

sys.path.insert(0, "/app")

from tests.e2e.test_assembled_table_pdf import FIXTURE_A, _extract_table

table = _extract_table(FIXTURE_A)
for i, row in enumerate(table.grid):
    cells = []
    for cell in row:
        t = " ".join(
            s.text.strip() for c in cell.content for il in c.inlines for s in il.spans
        )
        cells.append(t)
    print(i, cells)
