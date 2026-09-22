"""Debug-only: render a crop of FIXTURE_B's source PDF around the
'Quiescent Current' / 'with line' / 'with load' rows for visual ground
truth. Run with python3, not pytest."""
import sys
from pathlib import Path

sys.path.insert(0, "/app")

import fitz

from tests.e2e.test_assembled_table_pdf import FIXTURE_B

OUT_DIR = Path("/app/debug_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

d = fitz.open(str(FIXTURE_B))
p = d[0]
rect = fitz.Rect(0, p.rect.height * 0.40, p.rect.width, p.rect.height * 0.50)
pix = p.get_pixmap(clip=rect, matrix=fitz.Matrix(4, 4))
pix.save(OUT_DIR / "fixture_b_quiescent_crop.png")
print("saved ->", OUT_DIR / "fixture_b_quiescent_crop.png")

for b in p.get_text("dict", clip=rect)["blocks"]:
    for line in b.get("lines", []):
        for span in line["spans"]:
            print(f"  x0={span['bbox'][0]:.1f} y0={span['bbox'][1]:.1f} text={span['text']!r}")
