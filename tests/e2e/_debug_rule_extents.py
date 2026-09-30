"""Debug-only: every horizontal rule the analyzer measured, with how far
it runs, beside the rows of the grid it falls between.

Run with python3 (argument A or B), not pytest.
"""
import sys
sys.path.insert(0, "/app")
from src.assembler.latex_builder import _cell_text
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

PW, PH = 595.276, 841.89
fx = FIXTURE_A if (sys.argv[1:] or ["A"])[0] == "A" else FIXTURE_B
t = _extract_table(fx)
md = t.metadata or {}
print("verticals:", " ".join(f"{x * PW:.1f}" for x in md.get("column_rule_x", [])))
events = [(y, "RULE", f"x {e[0] * PW:6.1f}..{e[1] * PW:6.1f}")
          for y, e in zip(md.get("rule_y", []), md.get("rule_x_extent", []))]
for i, row in enumerate(t.grid):
    boxes = [c.visual_layout.bounding_box for c in row if c.visual_layout and c.visual_layout.bounding_box]
    if not boxes:
        continue
    y0 = min(b.y0 for b in boxes)
    y1 = max(b.y1 for b in boxes)
    cells = " | ".join(
        f"{_cell_text(c).strip()[:18]}@{c.visual_layout.bounding_box.x0 * PW:.0f}"
        for c in row if _cell_text(c).strip() and c.visual_layout and c.visual_layout.bounding_box
    )
    events.append((y0, f"row {i:2d}", f"y {y0 * PH:6.1f}..{y1 * PH:6.1f}  {cells}"))
for y, kind, text in sorted(events):
    print(f"{y * PH:7.1f}  {kind:7s} {text}")
print("text under each rule, top..bottom pt:",
      " ".join("-" if b is None else f"{b[0]:.1f}..{b[1]:.1f}" for b in md.get("text_band_pt", [])))
