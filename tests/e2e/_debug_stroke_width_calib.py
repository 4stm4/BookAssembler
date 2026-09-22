"""Debug-only: measure real glyph stroke width from the scanned page
pixels (not font metadata, which lies for OCR'd scans - see the
Times-Roman/non-bold flags on FIXTURE_A's own visibly-bold text) for
both fixtures' table regions, to calibrate a general is_bold-from-scan
threshold. Run with python3, not pytest."""
import sys

sys.path.insert(0, "/app")

import fitz
import numpy as np

from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

_INK_THRESHOLD = 160


def _median_stroke_pt(fitz_mod, pdf_path, page_index, rect, font_size_pt, zoom=6.0):
    d = fitz_mod.open(str(pdf_path))
    p = d[page_index]
    pix = p.get_pixmap(clip=rect, matrix=fitz_mod.Matrix(zoom, zoom))
    d.close()
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = arr[:, :, 0].astype(np.int32)
    if pix.n >= 3:
        grey = (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3
    ink = grey < _INK_THRESHOLD
    # Cap run length at roughly the font's own em size in pixels - longer
    # runs are joined strokes/serifs/underlines, not a single stroke
    # crossing, and would bias the median upward.
    max_run_px = font_size_pt * zoom * 0.5
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
    median_px = float(np.median(runs))
    return median_px / zoom


table_a = _extract_table(FIXTURE_A)
bb_a = table_a.visual_layout.bounding_box
da = fitz.open(str(FIXTURE_A))
pa = da[0]
pw, ph = pa.rect.width, pa.rect.height
rect_a = fitz.Rect(bb_a.x0 * pw, bb_a.y0 * ph, bb_a.x1 * pw, bb_a.y0 * ph + 60)
da.close()
stroke_a = _median_stroke_pt(fitz, FIXTURE_A, 0, rect_a, 14.15)
print(f"FIXTURE_A: median stroke = {stroke_a:.3f}pt, font ~14.15pt, ratio = {stroke_a/14.15:.4f}")

table_b = _extract_table(FIXTURE_B)
bb_b = table_b.visual_layout.bounding_box
db = fitz.open(str(FIXTURE_B))
pb = db[0]
pw2, ph2 = pb.rect.width, pb.rect.height
rect_b = fitz.Rect(bb_b.x0 * pw2, bb_b.y0 * ph2, bb_b.x1 * pw2, bb_b.y0 * ph2 + 30)
db.close()
stroke_b = _median_stroke_pt(fitz, FIXTURE_B, 0, rect_b, 5.48)
print(f"FIXTURE_B: median stroke = {stroke_b:.3f}pt, font ~5.48pt, ratio = {stroke_b/5.48:.4f}")
