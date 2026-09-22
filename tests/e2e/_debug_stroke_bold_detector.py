"""Debug-only: the real stroke-width-based is_bold detector, tried as an
actual product change in src/adapters/pdf_adapter.py and reverted after
measuring it net-negative on both fixtures (see the commit message for
the numbers). Kept runnable here, standalone, so a future session that
wants to revisit "bold to match a scanned source's real print weight"
does not have to re-derive the measurement from scratch.

A scanned page's own invisible OCR text layer reports whatever the OCR
engine's font model happened to name and flag - confirmed on FIXTURE_A:
every span reads "Times-Roman", flags=4 (serif only, no bold bit), even
though the page's own pixels print visibly heavier strokes than that.
flags-based is_bold has nothing real to read there - this measures the
real ink instead.

Run with python3, not pytest.
"""
import sys

sys.path.insert(0, "/app")

import fitz
import numpy as np

from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

_STROKE_INK_THRESHOLD = 160
_STROKE_BOLD_PT = 1.7  # absolute point threshold - see the calib scripts'
# docstrings for why this is NOT normalised by font size (normalising was
# tried first and measured backwards: a small font's own thin strokes
# round up to whole rendered pixels even at high zoom, reading heavier
# than a genuinely bold, larger font's real print).


def _is_scanned_page(page) -> bool:
    try:
        images = page.get_images()
    except Exception:
        return False
    if not images:
        return False
    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    return len(drawings) == 0


def _measure_stroke_pt(page, rect, zoom=8.0):
    pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(zoom, zoom))
    if pix.width <= 0 or pix.height <= 0:
        return None
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    grey = (
        (arr[:, :, 0].astype(np.int32) + arr[:, :, 1] + arr[:, :, 2]) // 3
        if pix.n >= 3 else arr[:, :, 0].astype(np.int32)
    )
    ink = grey < _STROKE_INK_THRESHOLD
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
    return float(np.median(runs)) / zoom


def report(name, fixture):
    d = fitz.open(str(fixture))
    p = d[0]
    scanned = _is_scanned_page(p)
    page_dict = p.get_text("dict")
    bold_lines, total_lines = 0, 0
    for block in page_dict.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans or not "".join(s.get("text", "") for s in spans).strip():
                continue
            total_lines += 1
            flags_bold = bool(spans[0].get("flags", 0) & (1 << 4))
            is_bold = flags_bold
            if not flags_bold and scanned:
                stroke = _measure_stroke_pt(p, fitz.Rect(line["bbox"]))
                if stroke is not None:
                    is_bold = stroke > _STROKE_BOLD_PT
            if is_bold:
                bold_lines += 1
    d.close()
    print(f"{name}: scanned={scanned}  bold lines={bold_lines}/{total_lines}")


report("FIXTURE_A", FIXTURE_A)
report("FIXTURE_B", FIXTURE_B)
