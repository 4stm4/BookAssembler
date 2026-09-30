"""Debug-only: how tall the source prints its capitals and digits against
how tall the rebuild sets them - the ink height of all-caps / digit
cells, measured the same way on both pages.

Run with python3 (argument A or B), not pytest.
"""
import re
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "/app")
import fitz
import numpy as np
from src.assembler.latex_builder import _cell_text, build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import _INK_THRESHOLD

ZOOM = 8.0
CAPS = re.compile(r"^[A-Z0-9.]+$")


def ink_height(page, rect):
    pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(ZOOM, ZOOM))
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < _INK_THRESHOLD
    ink = ink[:, ink.mean(axis=0) < 0.8]          # no vertical rules
    rows = np.nonzero((ink.mean(axis=1) > 0.02) & (ink.mean(axis=1) < 0.6))[0]
    return (rows[-1] - rows[0] + 1) / ZOOM if rows.size else None


fx = FIXTURE_A if (sys.argv[1:] or ["A"])[0] == "A" else FIXTURE_B
t = _extract_table(fx)
src = fitz.open(str(fx))[0]
PW, PH = src.rect.width, src.rect.height
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[t])]))
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    out = fitz.open(compile_xelatex("t.tex", td))[1]
    seen = set()
    print("text            size   source ink h   rebuild ink h   ratio")
    for row in t.grid:
        for cell in row:
            text = _cell_text(cell).strip()
            if not CAPS.match(text) or text in seen or len(text) < 2:
                continue
            seen.add(text)
            b = cell.visual_layout.bounding_box
            s_h = ink_height(src, fitz.Rect(b.x0 * PW, b.y0 * PH - 1, b.x1 * PW, b.y1 * PH + 1))
            hits = out.search_for(text)
            o_h = ink_height(out, hits[0] + (0, -1, 0, 1)) if hits else None
            size = cell.visual_layout.style.font_size_pt
            if s_h and o_h:
                print(f"{text:14s} {size:5.2f}   {s_h:6.2f}         {o_h:6.2f}          {s_h / o_h:.2f}")
