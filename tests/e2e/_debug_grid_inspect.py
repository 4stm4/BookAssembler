"""Debug-only: print the actual extracted grid structure for FIXTURE_B so we
can compare row count against what is visually distinct in the source PDF,
and inspect the x0 clustering that decides column count.
Run directly with python3, not pytest."""
import sys
sys.path.insert(0, "/app")

from tests.e2e.test_assembled_table_pdf import FIXTURE_B, _extract_table

table = _extract_table(FIXTURE_B)
print(f"Total grid rows: {len(table.grid)}")
for i, row in enumerate(table.grid):
    parts = []
    for cell in row:
        text = " ".join(
            s.text.strip()
            for c in cell.content
            for il in c.inlines
            for s in il.spans
        )
        x0 = None
        if cell.visual_layout and cell.visual_layout.bounding_box:
            x0 = round(cell.visual_layout.bounding_box.x0, 4)
        newlines = text.count("\n")
        parts.append(f"[{text[:22]!r} x0={x0} rs={cell.row_span} cs={cell.col_span}]")
    print(i, " | ".join(parts))

print("\nSorted x0 values (for column bin clustering):")
x0s = []
for row in table.grid:
    for cell in row:
        if cell.visual_layout and cell.visual_layout.bounding_box:
            x0s.append(round(cell.visual_layout.bounding_box.x0, 4))
x0s.sort()
print(x0s)

print("\nGaps between consecutive sorted x0 values:")
for a, b in zip(x0s, x0s[1:]):
    gap = round(b - a, 4)
    marker = "  <-- NEW BIN (>0.03)" if gap >= 0.03 else ""
    if gap > 0.0001:
        print(f"  {a} -> {b}  gap={gap}{marker}")
