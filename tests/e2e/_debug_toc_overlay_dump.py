"""Debug-only: the source/assembled crops and mismatch heatmap that
test_toc_overlay.py computes, saved per source page to debug_output/ for
visual inspection. Reuses the test's own extraction, build and crop.

python3 tests/e2e/_debug_toc_overlay_dump.py
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import fitz

sys.path.insert(0, "/app")

from tests.e2e.test_toc_overlay import (
    TOC_A, TOC_B, TOC_C, _build_toc_pdf, _crop_rects, _extract_tocs, _page_texts,
)
from tests.e2e.test_visual_overlay import (
    _MASK_SIZE, _MATCH_REACH_PX, _ink_mask, _mask_mismatch, _near, _render_crop,
)

OUT_DIR = Path("/app/debug_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def dump(fixture_path, source_page):
    name = f"{fixture_path.stem}_p{source_page}"
    tocs = _extract_tocs(fixture_path)
    if not tocs:
        print(f"{name}: no table of contents extracted")
        return
    texts = _page_texts(tocs, source_page)
    pdf_path = Path(_build_toc_pdf(tocs, str(OUT_DIR), f"{fixture_path.stem}_rebuilt"))
    out_page, src_rect, out_rect = _crop_rects(fitz, fixture_path, source_page, pdf_path, texts)
    if src_rect is None or out_rect is None:
        print(f"{name}: could not locate the contents (source {src_rect}, rebuilt {out_rect})")
        return
    img_source = _render_crop(fitz, fixture_path, source_page, src_rect)
    img_output = _render_crop(fitz, pdf_path, out_page, out_rect)
    ma, mb = _ink_mask(img_source), _ink_mask(img_output)
    mismatch = _mask_mismatch(img_source, img_output)

    heat = np.full(ma.shape + (3,), 255, dtype=np.uint8)
    heat[ma | mb] = (0, 0, 0)
    heat[ma & ~_near(mb, _MATCH_REACH_PX)] = (255, 0, 0)
    heat[mb & ~_near(ma, _MATCH_REACH_PX)] = (0, 0, 255)
    W, H = _MASK_SIZE
    combo = Image.new("RGB", (W * 3 + 40, H + 40), "white")
    combo.paste(img_source.resize(_MASK_SIZE), (10, 30))
    combo.paste(img_output.resize(_MASK_SIZE), (W + 20, 30))
    combo.paste(Image.fromarray(heat), (W * 2 + 30, 30))
    draw = ImageDraw.Draw(combo)
    draw.text((10, 5), "SOURCE", fill="black")
    draw.text((W + 20, 5), f"ASSEMBLED (page {out_page + 1})", fill="black")
    draw.text((W * 2 + 30, 5), f"MISMATCH {mismatch:.1%} (red=missing blue=extra)", fill="black")
    combo.save(OUT_DIR / f"{name}_combined.png")
    print(f"{name}: mismatch={mismatch:.1%}")


if __name__ == "__main__":
    for path, page in [(TOC_A, 0), (TOC_B, 0), (TOC_C, 0), (TOC_C, 1), (TOC_C, 2)]:
        dump(path, page)
