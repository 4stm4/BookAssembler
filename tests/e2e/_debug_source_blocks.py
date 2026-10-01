"""Debug-only: the blocks PdfSourceAdapter hands the table detector, with
each block's lines and their boxes, before any analyzer runs.

Run with python3 (argument A or B), not pytest.
"""
import sys
sys.path.insert(0, "/app")
from src.adapters.pdf_adapter import PdfSourceAdapter
from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B

PW, PH = 595.276, 841.89
fx = FIXTURE_A if (sys.argv[1:] or ["A"])[0] == "A" else FIXTURE_B
doc = PdfSourceAdapter().parse(open(fx, "rb"), f"file://{fx}")
for n, child in enumerate(doc.root_containers[0].children):
    bb = child.visual_layout.bounding_box if child.visual_layout else None
    print(f"[{n}] {type(child).__name__} x {bb.x0 * PW:5.1f}..{bb.x1 * PW:5.1f} y {bb.y0 * PH:5.1f}..{bb.y1 * PH:5.1f}" if bb else f"[{n}]")
    for inline in getattr(child, "inlines", []) or []:
        b = inline.visual_layout.bounding_box if inline.visual_layout else None
        t = "".join(s.text for s in inline.spans)
        print(f"      x {b.x0 * PW:5.1f}..{b.x1 * PW:5.1f} y {b.y0 * PH:5.1f}  {t[:60]}" if b else f"      {t[:60]}")
