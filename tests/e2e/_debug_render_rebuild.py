"""Debug-only: render the rebuilt table's page of a fixture to a PNG in
debug_output (rebuild_<stem>.png), and print where its words landed.

python3 tests/e2e/_debug_render_rebuild.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import _build_single_table_pdf

pdf = Path(sys.argv[1])
with tempfile.TemporaryDirectory() as td:
    page = fitz.open(_build_single_table_pdf(_extract_table(pdf), td, "render"))[1]
    page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(f"/app/debug_output/rebuild_{pdf.stem}.png")
    for w in page.get_text("words")[:40]:
        print(f"{w[0]:6.1f} {w[1]:6.1f} {w[2]:6.1f} {w[3]:6.1f}  {w[4]}")
