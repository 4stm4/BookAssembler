"""Debug-only: where the words of one printed line start, read off the ink
of the overlay crops (gaps over 2pt split words), source against rebuild,
in the source crop's points.

python3 tests/e2e/_debug_word_starts.py <pdf> <y0> <y1>   (crop points)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

import fitz
import numpy as np

from tests.e2e.test_assembled_table_pdf import _extract_table
from tests.e2e.test_visual_overlay import (
    _build_single_table_pdf, _output_table_rect, _render_crop, _source_table_rect, _table_texts,
)

ZOOM = 6.0
pdf, y0, y1 = Path(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
table = _extract_table(pdf)


def starts(img, height_pt):
    grey = np.asarray(img.convert("L"), dtype=np.uint8)
    k = height_pt / grey.shape[0]
    band = (grey[int(y0 / k):int(y1 / k)] < 160).any(axis=0)
    xs = np.flatnonzero(band)
    out, prev = [], None
    for x in xs:
        if prev is None or (x - prev) * k > 2.0:
            out.append(x * k)
        prev = x
    return out


with tempfile.TemporaryDirectory() as td:
    out = Path(_build_single_table_pdf(table, td, "ws"))
    src_rect = _source_table_rect(fitz, pdf, 0, table)
    s = starts(_render_crop(fitz, pdf, 0, src_rect, ZOOM), src_rect.height)
    o = starts(_render_crop(fitz, out, 1, _output_table_rect(fitz, out, 1, _table_texts(table)), ZOOM), src_rect.height)
print("src", " ".join(f"{v:.1f}" for v in s))
print("out", " ".join(f"{v:.1f}" for v in o))
