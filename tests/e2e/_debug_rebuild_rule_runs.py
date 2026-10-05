"""Debug-only: the horizontal rules the REBUILD actually printed, with
where each one starts and ends, read from its rendered pixels.

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
from tests.e2e._debug_crops import _output_table_rect

ZOOM = 4.0
fx = FIXTURE_A if (sys.argv[1:] or ["A"])[0] == "A" else FIXTURE_B
t = _extract_table(fx)
tex = build_latex(KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[t])]))
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex)
    pdf = Path(compile_xelatex("t.tex", td))
    rect = _output_table_rect(fitz, pdf, 1, _table_texts(t))
    d = fitz.open(str(pdf))
    pix = d[1].get_pixmap(clip=rect, matrix=fitz.Matrix(ZOOM, ZOOM))
arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
ink = arr[:, :, :3].mean(axis=2) < _INK_THRESHOLD
prev = None
for y in range(ink.shape[0]):
    xs = np.nonzero(ink[y])[0]
    runs, start = [], None
    for a, b in zip(xs, list(xs[1:]) + [None]):
        start = a if start is None else start
        if b is None or b - a > 1:
            if (a - start) / ZOOM > 20:
                runs.append((start / ZOOM, (a + 1) / ZOOM))
            start = None
    key = tuple(round(r[0]) for r in runs)
    if runs and key != prev:
        print(f"y {y / ZOOM:6.1f}: " + " ".join(f"{a:.1f}..{b:.1f}" for a, b in runs))
    prev = key if runs else None
