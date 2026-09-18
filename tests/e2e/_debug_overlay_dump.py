"""Debug-only: dump the same source/output crops and mismatch heatmap that
test_visual_overlay.py computes, to a fixed output directory, for visual
inspection. Not a test - reuses the real extraction/build/compile pipeline
functions, just adds a save step. Run directly with `python3`, not pytest.
"""
import sys
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
    _output_table_rect,
    _render_crop,
    _ink_mask,
    _MASK_SIZE,
    _INK_THRESHOLD,
)

OUT_DIR = Path("/app/debug_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def dump(fixture_path, name, source_page=0):
    table = _extract_table(fixture_path)
    texts = _table_texts(table)

    tex = build_latex(
        KnowledgeDocument(
            title=name,
            root_containers=[ContainerUnit(title="", level=1, children=[table])],
        )
    )
    tex_path = OUT_DIR / f"{name}.tex"
    tex_path.write_text(tex)
    pdf_path = compile_xelatex(f"{name}.tex", str(OUT_DIR))

    src_rect = _source_table_rect(fitz, fixture_path, source_page, table)
    out_rect = _output_table_rect(fitz, Path(pdf_path), 1, texts)
    if out_rect is None:
        print(f"{name}: could not locate assembled table")
        return

    img_source = _render_crop(fitz, fixture_path, source_page, src_rect)
    img_output = _render_crop(fitz, Path(pdf_path), 1, out_rect)
    img_source.save(OUT_DIR / f"{name}_source.png")
    img_output.save(OUT_DIR / f"{name}_output.png")

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
    heat.save(OUT_DIR / f"{name}_heatmap.png")

    # Combined side-by-side for convenience
    src_n = img_source.resize(_MASK_SIZE)
    out_n = img_output.resize(_MASK_SIZE)
    combo = Image.new("RGB", (W * 3 + 40, H + 40), "white")
    combo.paste(src_n, (10, 30))
    combo.paste(out_n, (W + 20, 30))
    combo.paste(heat, (W * 2 + 30, 30))
    draw = ImageDraw.Draw(combo)
    draw.text((10, 5), "SOURCE", fill="black")
    draw.text((W + 20, 5), "ASSEMBLED", fill="black")
    draw.text((W * 2 + 30, 5), f"MISMATCH {mismatch:.1%} (red=missing blue=extra)", fill="black")
    combo.save(OUT_DIR / f"{name}_combined.png")

    print(f"{name}: mismatch={mismatch:.1%}  -> {OUT_DIR}/{name}_combined.png")


if __name__ == "__main__":
    dump(FIXTURE_A, "fixture_a")
    dump(FIXTURE_B, "fixture_b")
