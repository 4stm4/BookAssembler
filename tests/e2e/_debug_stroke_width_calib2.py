"""Debug-only: compare SOURCE stroke width against OUR OWN ASSEMBLED
(regular-weight) render's stroke width, same method, same fixtures -
an apples-to-apples signal for whether the source is genuinely bolder
than what we're currently rendering, rather than an absolute
font-size-normalized threshold (which the first calibration attempt
showed is noisy across very different point sizes). Run with python3,
not pytest."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table
from tests.e2e.test_visual_overlay import _table_texts, _source_table_rect, _output_table_rect

_INK_THRESHOLD = 160


def _median_stroke_pt(pdf_path, page_index, rect, zoom=6.0):
    d = fitz.open(str(pdf_path))
    p = d[page_index]
    pix = p.get_pixmap(clip=rect, matrix=fitz.Matrix(zoom, zoom))
    d.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3 if pix.n >= 3 else arr[:, :, 0]
    ink = grey < _INK_THRESHOLD
    max_run_px = rect.height * zoom * 0.15
    runs = []
    for row in ink:
        run = 0
        for v in row:
            if v:
                run += 1
            else:
                if 0 < run <= max_run_px:
                    runs.append(run)
                run = 0
        if 0 < run <= max_run_px:
            runs.append(run)
    if not runs:
        return None
    return float(np.median(runs)) / zoom


def measure(name, fixture):
    table = _extract_table(fixture)
    texts = _table_texts(table)
    doc = KnowledgeDocument(
        title="t", root_containers=[ContainerUnit(title="", level=1, children=[table])]
    )
    tex = build_latex(doc)
    src_rect = _source_table_rect(fitz, fixture, 0, table)
    with tempfile.TemporaryDirectory() as td:
        Path(td, "t.tex").write_text(tex)
        pdf = compile_xelatex("t.tex", td)
        out_rect = _output_table_rect(fitz, Path(pdf), 1, texts)

        # First data row's own strip only, not the whole table, to avoid
        # border-line runs dominating the median.
        src_strip = fitz.Rect(src_rect.x0, src_rect.y0, src_rect.x1, src_rect.y0 + (src_rect.height / 10))
        out_strip = fitz.Rect(out_rect.x0, out_rect.y0, out_rect.x1, out_rect.y0 + (out_rect.height / 10))
        s_src = _median_stroke_pt(fixture, 0, src_strip)
        s_out = _median_stroke_pt(Path(pdf), 1, out_strip)
        print(f"{name}: source stroke={s_src:.3f}pt  assembled(regular) stroke={s_out:.3f}pt  ratio(src/out)={s_src/s_out:.3f}")


measure("FIXTURE_A", FIXTURE_A)
measure("FIXTURE_B", FIXTURE_B)
