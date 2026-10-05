"""Debug-only: the overlay test's measurement on any fixture PDF - the
real extraction and build, both crops cut as test_visual_overlay cuts
them - saving the ink mask (red source only, blue rebuild only, black
both) and the source above the rebuild.

Run with python3 <fixture.pdf> [table index], not pytest.
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "/app")
import fitz
import numpy as np
from PIL import Image
from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import (
    _MASK_SIZE, _MATCH_REACH_PX, _build_single_table_pdf, _crop_rects, _ink_mask, _mask_mismatch, _near,
    _render_crop, _table_texts,
)

fx = Path(sys.argv[1])
t = _extract_table(fx, index=int(sys.argv[2]) if len(sys.argv) > 2 else 0)
with tempfile.TemporaryDirectory() as td:
    pdf = Path(_build_single_table_pdf(t, td, "overlay_doc"))
    s, o = _crop_rects(fitz, fx, 0, Path(pdf), t)
    a, b = _render_crop(fitz, fx, 0, s), _render_crop(fitz, pdf, 1, o)
    ma, mb = _ink_mask(a), _ink_mask(b)
    print(f"{fx.name}: source crop {s.width:.1f}x{s.height:.1f}  rebuild crop {o.width:.1f}x{o.height:.1f}"
          f"  mismatch {_mask_mismatch(a, b):.1%}")
    W, H = _MASK_SIZE
    img = np.full((H, W, 3), 255, dtype=np.uint8)
    img[ma | mb] = (0, 0, 0)
    img[ma & ~_near(mb, _MATCH_REACH_PX)] = (220, 0, 0)
    img[mb & ~_near(ma, _MATCH_REACH_PX)] = (0, 0, 220)
    out = Path("/app/debug_output")
    Image.fromarray(img).resize((W * 2, H * 2), Image.NEAREST).save(out / f"mask_{fx.stem}.png")
    a4, b4 = _render_crop(fitz, fx, 0, s, 3.0), _render_crop(fitz, pdf, 1, o, 3.0).resize(_render_crop(fitz, fx, 0, s, 3.0).size)
    sheet = Image.new("RGB", (a4.width, a4.height * 2 + 20), "white")
    sheet.paste(a4, (0, 0))
    sheet.paste(b4, (0, a4.height + 20))
    sheet.save(out / f"svr_{fx.stem}.png")
