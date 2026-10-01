"""Build a scanned-page fixture from a source image.

The fixtures are what a scanned datasheet page is: the page as one image,
with an OCR text layer laid invisibly over it. This places the source image
on an A4 page - scaled so it is `width` points wide, or shorter where the
page height would not take it - and has tesseract write the text layer.

Needs tesseract (eng) next to PyMuPDF; the project image does not carry it.

    python3 tests/fixtures/build_scanned_fixture.py SRC OUT [width_pt] [psm]

psm is tesseract's page segmentation mode (default 3). The page is
binarized adaptively (Sauvola): tesseract's default single threshold for
the whole page, set mostly by its white margins, turned the architecture
diagram's coloured boxes black with their text, and read six words of it.
"""
import subprocess
import sys

import pymupdf
from PIL import Image

A4_W, A4_H = 595, 842
MAX_HEIGHT_PT = 760          # leaves the page's top and bottom margins clear
TOP_SHARE = 0.10             # where the image starts, as a share of the page
MIN_DPI = 250


def build(src: str, out: str, width_pt: float = 500.0, psm: int = 3) -> None:
    image = Image.open(src).convert("RGBA")
    flat = Image.new("RGB", image.size, "white")
    flat.paste(image, mask=image.split()[3])
    width_pt = min(width_pt, MAX_HEIGHT_PT * image.width / image.height)
    # Scanned at no less than MIN_DPI: a small source scaled up first, or
    # tesseract misses most of its small type (the architecture diagram
    # read six words at 130 dpi).
    scale = max(1.0, MIN_DPI / (image.width / width_pt * 72))
    if scale > 1.0:
        flat = flat.resize((round(flat.width * scale), round(flat.height * scale)), Image.LANCZOS)
    dpi = round(flat.width / width_pt * 72)
    page = Image.new("RGB", (round(A4_W / 72 * dpi), round(A4_H / 72 * dpi)), "white")
    page.paste(flat, ((page.width - flat.width) // 2, round(page.height * TOP_SHARE)))
    scan = out + ".page.png"
    page.save(scan, dpi=(dpi, dpi))
    # The tesseract command, not PyMuPDF's built-in call to it: on the
    # orange index page the built-in call returned an empty text layer
    # where the command reads every line.
    base = out[:-4] if out.endswith(".pdf") else out
    subprocess.run(["tesseract", scan, base, "-l", "eng", "--dpi", str(dpi), "--psm", str(psm),
                    "-c", "thresholding_method=2", "pdf"],
                   check=True, capture_output=True)
    pdf = pymupdf.open(base + ".pdf")
    print(f"{out}: {dpi} dpi, {pdf[0].rect}, {len(pdf[0].get_text('words'))} words")


if __name__ == "__main__":
    build(
        sys.argv[1], sys.argv[2],
        float(sys.argv[3]) if len(sys.argv) > 3 else 500.0,
        int(sys.argv[4]) if len(sys.argv) > 4 else 3,
    )
