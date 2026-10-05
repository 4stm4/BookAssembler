"""Debug-only: every cell of a fixture's extracted table - its span, box,
text and the metadata the builder sets it by.

python3 tests/e2e/_debug_table_cells.py <pdf> [rows]
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app")
from src.assembler.latex_builder import _cell_text
from tests.e2e.test_assembled_table_pdf import _extract_table

t = _extract_table(Path(sys.argv[1]))
rows = int(sys.argv[2]) if len(sys.argv) > 2 else len(t.grid)
print("table md", {k: v for k, v in (t.metadata or {}).items() if not isinstance(v, (list, dict))})
for i, row in enumerate(t.grid[:rows]):
    for j, cell in enumerate(row):
        b = cell.visual_layout.bounding_box if cell.visual_layout else None
        box = f"{b.x0 * 595:5.0f}{b.y0 * 842:5.0f}{b.x1 * 595:5.0f}{b.y1 * 842:5.0f}" if b else "-"
        md = {k: v for k, v in (cell.metadata or {}).items() if k != "line_words"}
        print(f"r{i} c{j} {getattr(cell, 'row_span', 1)}x{getattr(cell, 'col_span', 1)} {box} "
              f"{_cell_text(cell)!r:40} {md}")
