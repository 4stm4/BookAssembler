"""Debug-only: what ink is left in a table once its cells and rules are gone?

The decimal/binary fixture prints ~11 placeholder dots; its OCR layer
recognised 5, and all 5 are already cells. The other six exist only as
pixels. This lists every blob of ink that is outside every cell (boxes
expanded by a margin, to swallow glyph overhang the OCR box clips) and
off every rule, with its size and fill, so the thresholds for "this is
a dot" come from measurement rather than a guess.

Run with python3, not pytest.
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import pymupdf

from tests.e2e.test_assembled_table_pdf import FIXTURE_A, FIXTURE_B, _extract_table

ZOOM = 3.0
PAD = 20.0
MARGIN_PT = 1.5


def blobs(mask):
    seen = np.zeros_like(mask, dtype=bool)
    h, w = mask.shape
    out = []
    for y, x in np.argwhere(mask):
        if seen[y, x]:
            continue
        stack = [(y, x)]
        seen[y, x] = True
        pts = []
        while stack:
            cy, cx = stack.pop()
            pts.append((cy, cx))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        out.append(pts)
    return out


def run(name, fixture):
    table = _extract_table(fixture)
    doc = pymupdf.open(str(fixture))
    page = doc[table.visual_layout.page_or_screen_index or 0]
    pw, ph = page.rect.width, page.rect.height
    bb = table.visual_layout.bounding_box
    clip = pymupdf.Rect(bb.x0 * pw - PAD, bb.y0 * ph - PAD, bb.x1 * pw + PAD, bb.y1 * ph + PAD) & page.rect
    pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), clip=clip)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    ink = arr[:, :, :3].mean(axis=2) < 160
    H, W = ink.shape
    tw = (min(bb.x1 * pw, clip.x1) - max(bb.x0 * pw, clip.x0)) * ZOOM
    th = (min(bb.y1 * ph, clip.y1) - max(bb.y0 * ph, clip.y0)) * ZOOM
    for y in np.where(ink.sum(axis=1) > 0.6 * tw)[0]:
        ink[max(0, y - 2):y + 3, :] = False
    for x in np.where(ink.sum(axis=0) > 0.6 * th)[0]:
        ink[:, max(0, x - 2):x + 3] = False
    heights = []
    for row in table.grid:
        for c in row:
            b = c.visual_layout.bounding_box if c.visual_layout else None
            if b is None:
                continue
            heights.append((b.y1 - b.y0) * ph)
            x0 = int(((b.x0 * pw - MARGIN_PT) - clip.x0) * ZOOM)
            x1 = int(((b.x1 * pw + MARGIN_PT) - clip.x0) * ZOOM) + 1
            y0 = int(((b.y0 * ph - MARGIN_PT) - clip.y0) * ZOOM)
            y1 = int(((b.y1 * ph + MARGIN_PT) - clip.y0) * ZOOM) + 1
            ink[max(0, y0):y1, max(0, x0):x1] = False
    # only inside the table's own box
    bx0 = int((bb.x0 * pw - clip.x0) * ZOOM); bx1 = int((bb.x1 * pw - clip.x0) * ZOOM)
    by0 = int((bb.y0 * ph - clip.y0) * ZOOM); by1 = int((bb.y1 * ph - clip.y0) * ZOOM)
    inside = np.zeros_like(ink); inside[by0:by1, bx0:bx1] = True
    ink &= inside
    text_h = sorted(heights)[len(heights) // 2]
    print("=" * 70)
    print(f"{name}: median cell height {text_h:.2f}pt, leftover ink px {int(ink.sum())}")
    found = blobs(ink)
    print(f"  blobs: {len(found)}")
    print("   cx(pt)  cy(pt)   w(pt)  h(pt)  fill   n")
    for pts in sorted(found, key=len, reverse=True)[:40]:
        ys = [p[0] for p in pts]; xs = [p[1] for p in pts]
        bw = (max(xs) - min(xs) + 1) / ZOOM; bh = (max(ys) - min(ys) + 1) / ZOOM
        fill = len(pts) / ((max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1))
        cx = clip.x0 + (sum(xs) / len(xs)) / ZOOM; cy = clip.y0 + (sum(ys) / len(ys)) / ZOOM
        print(f"  {cx:7.1f} {cy:7.1f}  {bw:5.2f}  {bh:5.2f}  {fill:4.2f} {len(pts):4d}")
    doc.close()


run("FIXTURE_A", FIXTURE_A)
run("FIXTURE_B", FIXTURE_B)
