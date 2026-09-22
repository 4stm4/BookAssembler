"""Debug-only: measure each column's real x-range in FIXTURE_B's source
PDF via its header cell and the row of text directly below it, to
compare against latex_builder's declared p{}cm widths. Run with
python3, not pytest."""
import sys

sys.path.insert(0, "/app")

import fitz

from tests.e2e.test_assembled_table_pdf import FIXTURE_B

d = fitz.open(str(FIXTURE_B))
p = d[0]

# Column separator vertical lines (drawings) give the real boundaries,
# more reliable than guessing from text extents alone.
drawings = p.get_drawings()
xs = set()
for dr in drawings:
    for item in dr["items"]:
        if item[0] == "l":
            p0, p1 = item[1], item[2]
            if abs(p0.x - p1.x) < 0.5:  # vertical line
                xs.add(round(p0.x, 1))
print("vertical line x's near table (280-550y range):")
for dr in drawings:
    rect = dr.get("rect")
    if rect and 280 < rect.y0 < 470:
        for item in dr["items"]:
            if item[0] == "l":
                p0, p1 = item[1], item[2]
                if abs(p0.x - p1.x) < 0.5:
                    print(f"  x={p0.x:.1f} y0={p0.y:.1f} y1={p1.y:.1f}")
