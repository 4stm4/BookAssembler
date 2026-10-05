"""Debug-only: do the rebuild's vertical rules land where the source's are?

Both tables are cut exactly as test_visual_overlay cuts them, and every
vertical rule inside each crop is reported relative to the crop's left
edge, together with how far down the crop it runs. A column that comes
out wider or narrower than its source shows up as a growing offset.

Run with python3 (argument A or B), not pytest.
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "/app")
import fitz
import numpy as np
from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import (
    _INK_THRESHOLD, _table_texts,
)
from tests.e2e._debug_crops import _output_table_rect, _source_table_rect

ZOOM = 4.0
MIN_RUN = 0.08   # share of the crop's height a vertical run must cover


def verticals(pdf_path, page_index, rect):
    """(x from crop left, share of crop height inked) per vertical rule."""
    d = fitz.open(str(pdf_path))
    pix = d[page_index].get_pixmap(clip=rect, matrix=fitz.Matrix(ZOOM, ZOOM))
    d.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < _INK_THRESHOLD
    # longest unbroken vertical ink run per pixel column
    best = np.zeros(ink.shape[1])
    run = np.zeros(ink.shape[1])
    for row in ink:
        run = np.where(row, run + 1, 0)
        best = np.maximum(best, run)
    cols = np.where(best > MIN_RUN * ink.shape[0])[0]
    out, start, prev = [], None, None
    for c in list(cols) + [None]:
        if start is None:
            start = prev = c
        elif c is None or c - prev > 1:
            out.append(((start + prev) / 2.0 / ZOOM, best[start:prev + 1].max() / ink.shape[0]))
            start = prev = c
        else:
            prev = c
    return out


def run(name, fixture):
    t = _extract_table(fixture)
    tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[t])]))
    src_rect = _source_table_rect(fitz, fixture, 0, t)
    s = verticals(fixture, 0, src_rect)
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        out_rect = _output_table_rect(fitz, Path(pdf), 1, _table_texts(t))
        o = verticals(Path(pdf), 1, out_rect)
    print(f"{name}: crop width source {src_rect.width:.1f}  rebuild {out_rect.width:.1f}")
    print(f"   source  x: " + " ".join(f"{x:.1f}({h:.0%})" for x, h in s))
    print(f"   rebuild x: " + " ".join(f"{x:.1f}({h:.0%})" for x, h in o))


if __name__ == "__main__":
    which = sys.argv[1:] or ["A", "B"]
    for n, fx in (("A", FIXTURE_A), ("B", FIXTURE_B)):
        if n in which:
            run(n, fx)
