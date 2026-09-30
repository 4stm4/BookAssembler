"""Debug-only: overlay source and rebuild cropped by their OWN table frames.

Both sides of the old "fair" crop were not built the same way: the
source crop is the table's KRM box with no margin, while the rebuild
crop was its text extent PLUS 4pt left/right/bottom and 2pt top - so
every rebuild pixel sat shifted right and down by that margin, and no
border could coincide however well it was placed.

Here each side is cut to its own outer rules - the source's as the
analyzer measured them (table_rule_x0/x1/y0/y1), the rebuild's from the
PDF's own vector strokes - and both are scaled to the same mask. What
does not line up in this picture is the layout, not the crop.

Run with python3, not pytest.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import numpy as np
import pymupdf
from PIL import Image

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import _render_crop, _ink_mask, _MASK_SIZE

OUT = Path("/app/debug_output")


def source_frame(page, table):
    md = table.metadata or {}
    bb = table.visual_layout.bounding_box
    pw, ph = page.rect.width, page.rect.height
    x0 = md.get("table_rule_x0", bb.x0) * pw
    x1 = md.get("table_rule_x1", bb.x1) * pw
    y0 = md.get("table_rule_y0", bb.y0) * ph
    y1 = md.get("table_rule_y1", bb.y1) * ph
    return pymupdf.Rect(x0, y0, x1, y1)


def rebuild_frame(page):
    xs, ys = [], []
    for d in page.get_drawings():
        r = d["rect"]
        if r.height > 20 and r.width < 3:
            xs.append((r.x0 + r.x1) / 2)
        if r.width > 20 and r.height < 3:
            ys.append((r.y0 + r.y1) / 2)
    return pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))


def run(name, fixture):
    table = _extract_table(fixture)
    src_doc = pymupdf.open(str(fixture))
    s_rect = source_frame(src_doc[0], table)
    src_doc.close()
    tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]))
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        out_doc = pymupdf.open(pdf)
        o_rect = rebuild_frame(out_doc[1])
        out_doc.close()
        a = _ink_mask(_render_crop(pymupdf, fixture, 0, s_rect))
        b = _ink_mask(_render_crop(pymupdf, Path(pdf), 1, o_rect))
    mism = float((a ^ b).sum()) / a.size
    print(f"{name}: source frame {s_rect.width:.1f}x{s_rect.height:.1f}  "
          f"rebuild frame {o_rect.width:.1f}x{o_rect.height:.1f}  mismatch {mism:.1%}")
    W, H = _MASK_SIZE
    img = np.full((H, W, 3), 255, dtype=np.uint8)
    img[a & b] = (0, 0, 0)
    img[a & ~b] = (220, 0, 0)
    img[b & ~a] = (0, 0, 220)
    path = OUT / f"frame_overlay_{name.lower()}.png"
    Image.fromarray(img).resize((W * 2, H * 2), Image.NEAREST).save(path)
    print(f"   saved {path}")


run("A", FIXTURE_A)
run("B", FIXTURE_B)
