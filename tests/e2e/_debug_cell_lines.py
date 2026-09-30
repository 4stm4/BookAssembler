"""Debug-only: every cell whose text holds more than one printed line,
with its lines as the analyzer kept them.

Run with python3 (argument A or B), not pytest.
"""
import sys
sys.path.insert(0, "/app")
from src.assembler.latex_builder import _cell_text
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

PH = 841.89
fx = FIXTURE_A if (sys.argv[1:] or ["A"])[0] == "A" else FIXTURE_B
t = _extract_table(fx)
for i, row in enumerate(t.grid):
    for j, cell in enumerate(row):
        text = _cell_text(cell)
        box = cell.visual_layout.bounding_box if cell.visual_layout else None
        size = cell.visual_layout.style.font_size_pt if cell.visual_layout and cell.visual_layout.style else None
        tall = box is not None and size and (box.y1 - box.y0) * PH > 1.5 * 1.2 * size
        if "\n" in text or tall:
            print(f"row {i} cell {j}: h {(box.y1 - box.y0) * PH:.1f}pt size {size}  {text!r}")
