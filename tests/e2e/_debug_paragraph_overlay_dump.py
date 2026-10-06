"""Debug-only: test_paragraph_overlay's measurement on a fixture - every
paragraph the pipeline reads, its text, the two crops and its share of
missed ink - saving each paragraph's source / rebuild / mask side by side
to debug_output/.

python3 tests/e2e/_debug_paragraph_overlay_dump.py <pdf>
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
import fitz
import numpy as np
from PIL import Image, ImageDraw

from tests.e2e.test_paragraph_overlay import (
    _build_pdf, _crop_rects, _extract, _paragraph_text, _paragraphs,
)
from tests.e2e.test_toc_overlay import _MASK_SIZE, _MATCH_REACH_PX, _ink_mask, _mask_mismatch, _near
from tests.e2e.test_visual_overlay import _render_crop

fx = Path(sys.argv[1])
out = Path("/app/debug_output")
doc = _extract(fx)
paragraphs = _paragraphs(doc)
print(f"{fx.stem}: {len(paragraphs)} paragraphs")
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_pdf(doc, td, "p"))
    for k, p in enumerate(paragraphs):
        page, s, o = _crop_rects(fitz, fx, pdf, p)
        text = _paragraph_text(p)
        if s is None or o is None:
            print(f"  {k + 1}: not found (source {s}, rebuild {o}) {text[:60]!r}")
            continue
        a, b = _render_crop(fitz, fx, 0, s), _render_crop(fitz, pdf, page, o)
        m = _mask_mismatch(a, b)
        print(f"  {k + 1}: {m:6.1%}  src {s.width:.0f}x{s.height:.0f}  out {o.width:.0f}x{o.height:.0f}  {text[:60]!r}")
        ma, mb = _ink_mask(a), _ink_mask(b)
        heat = np.full(ma.shape + (3,), 255, dtype=np.uint8)
        heat[ma | mb] = (0, 0, 0)
        heat[ma & ~_near(mb, _MATCH_REACH_PX)] = (255, 0, 0)
        heat[mb & ~_near(ma, _MATCH_REACH_PX)] = (0, 0, 255)
        W, H = _MASK_SIZE
        combo = Image.new("RGB", (W * 3 + 40, H + 40), "white")
        combo.paste(a.resize(_MASK_SIZE), (10, 30))
        combo.paste(b.resize(_MASK_SIZE), (W + 20, 30))
        combo.paste(Image.fromarray(heat), (W * 2 + 30, 30))
        ImageDraw.Draw(combo).text((10, 5), f"SOURCE | ASSEMBLED (page {page + 1}) | MISMATCH {m:.1%}", fill="black")
        combo.save(out / f"{fx.stem}_p{k + 1}.png")
