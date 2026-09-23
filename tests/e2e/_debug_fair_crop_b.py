"""Debug-only: recompute the visual-overlay mismatch for FIXTURE_B with
the assembled crop measured WITHOUT the test's own top padding (the
max(row_h,12) subtraction in _output_table_rect) - source side reuses
_source_table_rect unchanged. Does NOT modify test_visual_overlay.py.
Run with python3, not pytest."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
from PIL import Image, ImageDraw

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _table_texts, _source_table_rect, _render_crop, _ink_mask, _MASK_SIZE,
)

OUT_DIR = Path("/app/debug_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

table = _extract_table(FIXTURE_B)
texts = _table_texts(table)
doc = KnowledgeDocument(
    title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
)
tex = build_latex(doc)
src_rect = _source_table_rect(fitz, FIXTURE_B, 0, table)


def _output_table_rect_no_padding(fitz_mod, pdf_path, page_index, texts):
    d = fitz_mod.open(pdf_path)
    page = d[page_index]
    strong = [t for t in texts if len(t) >= 6]
    rects = []
    for t in strong:
        rects.extend(page.search_for(t))
    d.close()
    if not rects:
        return None
    x0 = min(r.x0 for r in rects)
    y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y1 = max(r.y1 for r in rects)
    return fitz_mod.Rect(x0 - 4, y0 - 2, x1 + 4, y1 + 4)


with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = compile_xelatex("t.tex", td)
    out_rect_fair = _output_table_rect_no_padding(fitz, Path(pdf), 1, texts)

    print("src_rect (unchanged):", src_rect, "size:", src_rect.width, src_rect.height)
    print("out_rect (no padding):", out_rect_fair, "size:", out_rect_fair.width, out_rect_fair.height)

    img_source = _render_crop(fitz, FIXTURE_B, 0, src_rect)
    img_output = _render_crop(fitz, Path(pdf), 1, out_rect_fair)

ma = _ink_mask(img_source)
mb = _ink_mask(img_output)
mismatch = float((ma ^ mb).sum()) / float(ma.size)
print(f"FAIR (no test padding) mismatch: {mismatch:.4f} ({mismatch:.1%})")

only_src = ma & ~mb
only_out = mb & ~ma
W, H = _MASK_SIZE
heat = Image.new("RGB", _MASK_SIZE, "white")
for y in range(H):
    for x in range(W):
        if only_src[y, x]:
            heat.putpixel((x, y), (255, 0, 0))
        elif only_out[y, x]:
            heat.putpixel((x, y), (0, 0, 255))
        elif ma[y, x]:
            heat.putpixel((x, y), (0, 0, 0))

src_n = img_source.resize(_MASK_SIZE)
out_n = img_output.resize(_MASK_SIZE)
combo = Image.new("RGB", (W * 3 + 40, H + 40), "white")
combo.paste(src_n, (10, 30))
combo.paste(out_n, (W + 20, 30))
combo.paste(heat, (W * 2 + 30, 30))
draw = ImageDraw.Draw(combo)
draw.text((10, 5), "SOURCE", fill="black")
draw.text((W + 20, 5), "ASSEMBLED (no test top-padding)", fill="black")
draw.text((W * 2 + 30, 5), f"MISMATCH {mismatch:.1%} (fair, no padding)", fill="black")
combo.save(OUT_DIR / "fixture_b_fair_crop.png")
print("saved ->", OUT_DIR / "fixture_b_fair_crop.png")
