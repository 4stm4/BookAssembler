"""Debug-only: replicate _column_bins + nearest-bin assignment for
FIXTURE_B's real grid, to see which column each of row2/row4's cells
lands in. Run with python3, not pytest."""
import sys

sys.path.insert(0, "/app")

from src.assembler.latex_builder import _column_bins, _cell_x0
from tests.e2e.test_assembled_table_pdf import FIXTURE_B, _extract_table

table = _extract_table(FIXTURE_B)
grid = table.grid
bins = _column_bins(grid)
print("bins:", bins)

for ridx in (0, 2, 4):
    row = grid[ridx]
    print(f"row {ridx}:")
    for cell in row:
        x0 = _cell_x0(cell)
        col = min(range(len(bins)), key=lambda i: abs(bins[i] - x0))
        t = " ".join(s.text.strip() for c in cell.content for il in c.inlines for s in il.spans)
        print(f"  x0={x0:.4f} -> col={col} text={t!r}")
