"""DEBUG DUPLICATE: same tight-crop hypothesis as before (deleted after
disproof), but dumping the combined source/output/heatmap image this
time instead of only printing the mismatch number.
Not touching test_visual_overlay.py (TESTS_STOPLIST) - reuses its own
helpers directly. Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import fitz

sys.path.insert(0, "/app")

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _table_texts,
    _source_table_rect,
    _render_crop,
    _ink_mask,
    _MASK_SIZE,
    _build_single_table_pdf,
)

OUT_DIR = Path("/app/debug_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _output_table_rect_tight(fitz_mod, pdf_path, page_index, texts):
    doc = fitz_mod.open(pdf_path)
    page = doc[page_index]
    strong = [t for t in texts if len(t) >= 6]
    rects = []
    for t in strong:
        rects.extend(page.search_for(t))
    doc.close()
    if not rects:
        return None
    x0 = min(r.x0 for r in rects)
    y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y1 = max(r.y1 for r in rects)
    return fitz_mod.Rect(x0 - 4, y0 - 2, x1 + 4, y1 + 4)


def dump(fixture_path, name, source_page=0):
    table = _extract_table(fixture_path)
    texts = _table_texts(table)

    tex = build_latex(
        KnowledgeDocument(
            title=name,
            root_containers=[ContainerUnit(title="", level=1, children=[table])],
        )
    )
    with tempfile.TemporaryDirectory() as td:
        Path(td, f"{name}.tex").write_text(tex)
        pdf_path = compile_xelatex(f"{name}.tex", td)

        src_rect = _source_table_rect(fitz, fixture_path, source_page, table)
        out_rect = _output_table_rect_tight(fitz, Path(pdf_path), 1, texts)
        if out_rect is None:
            print(f"{name}: could not locate assembled table")
            return

        img_source = _render_crop(fitz, fixture_path, source_page, src_rect)
        img_output = _render_crop(fitz, Path(pdf_path), 1, out_rect)

    ma = _ink_mask(img_source)
    mb = _ink_mask(img_output)
    mismatch = float((ma ^ mb).sum()) / float(ma.size)

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
    draw.text((W + 20, 5), "ASSEMBLED (tight crop)", fill="black")
    draw.text((W * 2 + 30, 5), f"MISMATCH {mismatch:.1%} (tight-crop hypothesis)", fill="black")
    combo.save(OUT_DIR / f"{name}_tightcrop_combined.png")

    print(f"{name}: mismatch={mismatch:.1%}  -> {OUT_DIR}/{name}_tightcrop_combined.png")


if __name__ == "__main__":
    dump(FIXTURE_A, "fixture_a")
    dump(FIXTURE_B, "fixture_b")
