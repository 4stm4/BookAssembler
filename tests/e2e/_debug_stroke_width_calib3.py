"""Debug-only: measure stroke width strictly WITHIN one word's own tight
bbox (search_for), in both source and our regular-weight assembled
render, to avoid table border lines contaminating the run-length
statistic (the likely cause of the previous two calibration attempts'
counter-intuitive numbers - a table row's horizontal scan crosses
several vertical column rules, and each hairline crossing contributes
a short run that swamps real glyph-stroke runs when text is sparse).
Run with python3, not pytest."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

_INK_THRESHOLD = 160


def _median_stroke_pt(pdf_path, page_index, rect, zoom=10.0):
    d = fitz.open(str(pdf_path))
    p = d[page_index]
    pix = p.get_pixmap(clip=rect, matrix=fitz.Matrix(zoom, zoom))
    d.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3 if pix.n >= 3 else arr[:, :, 0]
    ink = grey < _INK_THRESHOLD
    runs = []
    for row in ink:
        run = 0
        for v in row:
            if v:
                run += 1
            else:
                if run > 0:
                    runs.append(run)
                run = 0
        if run > 0:
            runs.append(run)
    if not runs:
        return None
    return float(np.median(runs)) / zoom, len(runs)


def measure_word(name, source_pdf, source_word, assembled_pdf, assembled_page):
    sd = fitz.open(str(source_pdf))
    sp = sd[0]
    r = sp.search_for(source_word)
    sd.close()
    assert r, f"{source_word!r} not found in source"
    rect = r[0]
    s = _median_stroke_pt(source_pdf, 0, rect)

    od = fitz.open(str(assembled_pdf))
    op = od[assembled_page]
    r2 = op.search_for(source_word)
    od.close()
    assert r2, f"{source_word!r} not found in assembled"
    rect2 = r2[0]
    o = _median_stroke_pt(Path(assembled_pdf), assembled_page, rect2)

    print(f"{name} {source_word!r}: source stroke={s[0]:.4f}pt (n={s[1]})  assembled stroke={o[0]:.4f}pt (n={o[1]})  ratio={s[0]/o[0]:.3f}")


table_a = _extract_table(FIXTURE_A)
doc_a = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table_a])])
tex_a = build_latex(doc_a)
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex_a)
    pdf_a = compile_xelatex("t.tex", td)
    measure_word("FIXTURE_A", FIXTURE_A, "Decimal", pdf_a, 1)
    measure_word("FIXTURE_A", FIXTURE_A, "Binary", pdf_a, 1)

table_b = _extract_table(FIXTURE_B)
doc_b = KnowledgeDocument(title="t", root_containers=[ContainerUnit(title="", level=1, children=[table_b])])
tex_b = build_latex(doc_b)
with tempfile.TemporaryDirectory() as td:
    Path(td, "t.tex").write_text(tex_b)
    pdf_b = compile_xelatex("t.tex", td)
    measure_word("FIXTURE_B", FIXTURE_B, "CHARACTERISTICS", pdf_b, 1)
    measure_word("FIXTURE_B", FIXTURE_B, "CONDITIONS", pdf_b, 1)
