"""E2E: pixel-level visual assert between a source page's table of contents
and the same table of contents as extracted + reassembled through the real
pipeline - test_visual_overlay.py's check, for tables of contents.

test_toc_entry.py checks what the analyzer reads off a contents page - an
entry's number, title, page, level. This checks what no field assert can:
lay the rebuilt contents on top of the source page's and see whether the ink
lands in the same places - the entries' indents, their numbers set apart,
the leaders run to the page numbers, the descriptions under their titles.

Each source page is compared on its own: a contents list printed over three
pages is three overlays. The source page and the rebuilt page holding most
of its contents are cut the same way (_contents_rect), each to the
contents' own extent, and one ink matrix is laid over the other.

Its measure is its own, not test_visual_overlay's: the misses are counted
against the ink of either crop, not the crop's area (_mask_mismatch) - a
contents page is mostly white, and over its area a rebuild that had lost
every title disagreed on 9.3% - and a text is located by its ink, not by
the box its source guessed (_ink_of). The limit is 7% (MAX_MISMATCH).
"""

from pathlib import Path

import pytest

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument, TocEntryBlock
from tests.e2e.test_visual_overlay import _render_crop

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "toc"
TOC_A = FIXTURES / "toc_a.pdf"   # Intel "Contents": numbered entries, linked titles
TOC_B = FIXTURES / "toc_b.pdf"   # typewritten CONTENTS: sections, sub-entries, appendices
TOC_C = FIXTURES / "toc_c.pdf"   # "TABLE OF CONTENTS" over 3 pages: chapters, pages, descriptions

_GLYPH_CONTRAST = 120    # summed RGB difference from the paper or fill a glyph is set on
# A row or column this full of ink is a rule crossing the word, pads and
# all: a short word's own strokes fill most of its width ("PPI" at 0.6
# lost the rows through its bowls and was read 0.5pt high).
_TEXT_RULE_SPAN = 0.9
_BOX_CORE = 0.2          # of a box's height in from each edge: surely its own line
_LETTER_GAP = 0.12       # of a box's height: the widest gap between two letters of a word


def _ink_of(fitz, page, rect):
    """Where the ink of a text found at rect is.

    A found text's box is its source's guess, not its print: tesseract
    boxed the architecture fixture's "USER" 4.0pt above its ink, the
    rebuild's font 0.8pt above its own - and a crop cut from boxes shifted
    the rebuilt table 2-3pt against its source however exactly it was
    set. A glyph is what stands out from what it is printed on (paper, or
    a box's fill), darker; its line is the run of such rows through the
    box's middle, rules left out, and across it reaches as far as its ink
    runs on from the box.
    """
    import numpy as np
    zoom = 4.0
    clip = fitz.Rect(rect.x0 - rect.height / 2, rect.y0 - rect.height / 2,
                     rect.x1 + rect.height / 2, rect.y1 + rect.height / 2) & page.rect
    if clip.is_empty:
        return rect
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(int)
    ground = np.median(rgb.reshape(-1, 3), axis=0)
    ink = (np.abs(rgb - ground).sum(axis=2) > _GLYPH_CONTRAST) & (rgb.sum(axis=2) < ground.sum())
    ink[ink.mean(axis=1) > _TEXT_RULE_SPAN, :] = False
    ink[:, ink.mean(axis=0) > _TEXT_RULE_SPAN] = False
    rows = ink.any(axis=1)
    middle = min(max(int(((rect.y0 + rect.y1) / 2 - clip.y0) * zoom), 0), len(rows) - 1)
    if not rows[middle]:
        near = np.flatnonzero(rows)
        if not len(near):
            return rect
        middle = int(near[np.abs(near - middle).argmin()])
    top, bottom = middle, middle
    while top > 0 and rows[top - 1]:
        top -= 1
    while bottom < len(rows) - 1 and rows[bottom + 1]:
        bottom += 1
    # Lines set close touch, a descender on the ascender under it, and the
    # run goes on into the next line. Where it runs out past the box, it is
    # cut at its lightest row from the box's inner fifth on: where one line
    # ends and the next begins.
    density = ink.sum(axis=1)
    box_lo, box_hi = int((rect.y0 - clip.y0) * zoom), int((rect.y1 - clip.y0) * zoom)
    core_lo = int((rect.y0 + rect.height * _BOX_CORE - clip.y0) * zoom)
    core_hi = int((rect.y1 - rect.height * _BOX_CORE - clip.y0) * zoom)
    if bottom > box_hi:
        bottom = core_hi + int(np.argmin(density[core_hi + 1:bottom + 1]))
    if top < box_lo and core_lo > top:
        top = top + int(np.argmin(density[top:core_lo])) + 1
    # Across: the ink inside the box, run out to where it ends - a glyph
    # boxed short ("CONTENTS" lost its S to its box) - up to the space
    # before the next word.
    inked = ink[top:bottom + 1].any(axis=0)
    box_l = max(0, int((rect.x0 - clip.x0) * zoom))
    box_r = min(len(inked), int((rect.x1 - clip.x0) * zoom))
    cols = np.flatnonzero(inked[box_l:box_r])
    if not len(cols):
        return rect
    left, right = box_l + int(cols[0]), box_l + int(cols[-1])
    # over the gaps between letters, never a word space
    gap = max(1, int(rect.height * _LETTER_GAP * zoom))
    while left > 0 and inked[max(0, left - gap):left].any():
        left -= 1
    while right < len(inked) - 1 and inked[right + 1:right + 1 + gap].any():
        right += 1
    return fitz.Rect(clip.x0 + left / zoom, clip.y0 + top / zoom,
                     clip.x0 + (right + 1) / zoom, clip.y0 + (bottom + 1) / zoom)


_MASK_SIZE = (400, 600)  # both crops normalized to this before overlaying
_INK_THRESHOLD = 160     # 0-255 grey level below which a pixel counts as ink
# Ink within this many mask pixels of the other crop's ink lands on it. A
# crop laid over itself one pixel to the side disagrees on 42-64% of its
# ink: at 400x600 one pixel is a fraction of a stroke, and no rebuild can
# be placed closer than that to a scan.
_MATCH_REACH_PX = 1

# Share of the ink allowed to miss the other crop's ink. One number for
# every page on purpose: a rebuilt contents page either lands on top of the
# page it came from or it does not. 7%, by the maintainer's decision
# (2026-10-05).
MAX_MISMATCH = 0.07


def _ink_mask(img):
    """Binary "there is ink here" mask, normalized to a common size.

    Both crops are stretched to the same size first, so this compares WHERE
    the ink lands within each table, independent of the two documents'
    different page geometry and DPI.
    """
    import numpy as np
    grey = np.array(img.convert("L").resize(_MASK_SIZE), dtype=np.uint8)
    return grey < _INK_THRESHOLD


def _near(mask, reach: int):
    """Every pixel within reach pixels of the mask's ink."""
    import numpy as np
    h, w = mask.shape
    padded = np.pad(mask, reach)
    out = np.zeros_like(mask)
    for dy in range(2 * reach + 1):
        for dx in range(2 * reach + 1):
            out |= padded[dy:dy + h, dx:dx + w]
    return out


def _mask_mismatch(img_a, img_b) -> float:
    """Share of the ink that misses the other crop's ink (0.0 = every
    stroke lands on one).

    Both crops become a black/white matrix, laid one over the other; ink of
    either with no ink of the other within _MATCH_REACH_PX counts as a
    miss, and the misses are taken over the ink of either - not over the
    crop's whole area, which on a sparse page (a typewritten contents list)
    is mostly white the two crops share: there a rebuild that had lost
    every title disagreed on only 9.3% of the area.

    test_visual_overlay counts disagreeing pixels over the crop's area; on a
    contents page that measure let the lost titles pass. Misplaced ink is
    counted twice, once for being absent where the source
    has it and once for being present where the source does not.
    """
    ma = _ink_mask(img_a)
    mb = _ink_mask(img_b)
    miss = (ma & ~_near(mb, _MATCH_REACH_PX)) | (mb & ~_near(ma, _MATCH_REACH_PX))
    ink = (ma | mb).sum()
    return float(miss.sum()) / float(ink) if ink else 0.0


# Up to and including the analyzer that turns a contents page into entries;
# what runs after it reorganizes the document, not the contents list.
_STOP_AFTER = "BlockClassifierAnalyzer"


def _extract_tocs(pdf_path: Path) -> list:
    """The table-of-contents containers the real pipeline reads off a PDF."""
    from src.adapters.pdf_adapter import PdfSourceAdapter
    from src.analyzers import create_default_pipeline
    from src.analyzers.pipeline import PipelineRunner
    from src.graph.knowledge_graph import KnowledgeGraph
    from src.graph.reading_graph import ReadingGraph

    chain = []
    for analyzer in create_default_pipeline():
        chain.append(analyzer)
        if analyzer.manifest.name == _STOP_AFTER:
            break
    with open(pdf_path, "rb") as fh:
        doc = PdfSourceAdapter().parse(fh, f"file://{pdf_path}")
    PipelineRunner(chain).execute(doc, ReadingGraph(), KnowledgeGraph())

    tocs = []

    def walk(node):
        if isinstance(node, ContainerUnit):
            if node.semantic_type == "toc":
                tocs.append(node)
            for child in node.children:
                walk(child)

    for root in doc.root_containers:
        walk(root)
    return tocs


def _live_entries(toc: ContainerUnit) -> list:
    return [c for c in toc.children
            if isinstance(c, TocEntryBlock) and not c.is_tombstoned]


def _page_of(node):
    vl = getattr(node, "visual_layout", None)
    return vl.page_or_screen_index if vl else None


def _page_entries(tocs: list, page_index: int) -> list:
    """The live entries the analyzer read off one source page."""
    return [e for toc in tocs for e in _live_entries(toc) if _page_of(e) == page_index]


def _page_texts(tocs: list, page_index: int) -> list:
    """What the contents print on one source page, top to bottom: the
    heading of a contents list that starts there, then each entry's title
    and the rows of its description."""
    texts = []
    for toc in tocs:
        entries = _page_entries([toc], page_index)
        if toc.title and entries and _page_of(_live_entries(toc)[0]) == page_index:
            texts.append(toc.title)
        for e in entries:
            texts += (e.entry_text or "").split("\n")
            texts += (e.metadata or {}).get("toc_description") or []
    return [t.strip() for t in texts if t.strip()]


def _build_toc_pdf(tocs: list, work_dir: str, name: str) -> str:
    import os
    doc = KnowledgeDocument(
        title=name,
        root_containers=[ContainerUnit(title="", level=1, children=list(tocs))],
    )
    tex_path = os.path.join(work_dir, f"{name}.tex")
    with open(tex_path, "w") as fh:
        # Page by page, as the product assembles a book (translator,
        # API): a contents page is one of the pages rebuilt where they
        # were printed (RFC 0021 §3), not a run of lines in the flow.
        fh.write(build_latex(doc, page_aware=True))
    try:
        return compile_xelatex(f"{name}.tex", work_dir)
    except RuntimeError as exc:
        if "not found" in str(exc):
            pytest.skip(
                "local TeX Live is missing a package the preamble needs "
                f"(RFC 0021 SS4) - {exc}"
            )
        raise


_BASELINE_DENSITY = 0.3   # a row this dense against the line's densest is above its baseline
_BASELINE_FALL = 0.6      # the row under the baseline holds less than this of its ink


def _baseline_of(fitz, page, rect) -> float:
    """Where the ink at rect stands: down from its densest row, the first
    its ink falls away under by _BASELINE_FALL for good - from the line's
    body to its descenders."""
    import numpy as np
    zoom = 4.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(int)
    ground = np.median(rgb.reshape(-1, 3), axis=0)
    density = ((np.abs(rgb - ground).sum(axis=2) > 120) & (rgb.sum(axis=2) < ground.sum())).sum(axis=1)
    if not density.any():
        return rect.y1
    for r in range(int(np.argmax(density)), len(density)):
        rest = density[r + 1:].max() if r + 1 < len(density) else 0
        if density[r] >= _BASELINE_DENSITY * density.max() and rest < _BASELINE_FALL * density[r]:
            return rect.y0 + (r + 1) / zoom
    return rect.y1


def _contents_rect(fitz, pdf_path: Path, page_index: int, texts: list):
    """Locate one source page's contents on a page by their own text - the
    same way on the source page and on the assembled one.

    Top to bottom they run from the first of the texts found to the last's
    baseline, each looked for below the one before it: a title the list repeats
    ("Section") is the next one down, and a rebuilt page that runs on into
    the next source page's entries is cut where this page's end. Across,
    they take in every word printed between - a page number set off across
    a leader, a title the analyzer did not read, a description the rebuild
    dropped. Each text found stands for its ink, as in test_visual_overlay
    (_ink_of): a box is its source's guess.
    """
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    found, below = [], float("-inf")
    for t in texts:
        hits = sorted(page.search_for(t), key=lambda r: (r.y0, r.x0))
        hit = next((r for r in hits if r.y0 > below), None)
        if hit is not None:
            found.append(_ink_of(fitz, page, hit))
            # The next text stands on a later row: below this one's middle.
            below = (hit.y0 + hit.y1) / 2
    if not found:
        doc.close()
        return None
    # Down to the last text's baseline, not its ink's foot: how far a
    # descender reaches is its face's, and the rebuild's touches the line
    # under it where the print's does not.
    top, bottom = min(r.y0 for r in found), _baseline_of(fitz, page, found[-1])
    inside = found + [_ink_of(fitz, page, fitz.Rect(w[:4])) for w in page.get_text("words")
                      if top <= (w[1] + w[3]) / 2 <= bottom]
    doc.close()
    return fitz.Rect(min(r.x0 for r in inside), top, max(r.x1 for r in inside), bottom)


def _crop_rects(fitz, source_pdf: Path, source_page: int, rebuilt_pdf: Path, texts: list):
    """Where to cut the source page's contents and the rebuilt ones: both by
    _contents_rect, from the texts found on the source page AND on the
    rebuilt page holding most of them - the rebuild breaks its pages where
    its own type runs out, not where the source's did. Returns the rebuilt
    page's index with the two rects.

    A text either page cannot find bounds neither crop: the source's text
    layer can split a row the analyzer joined ("...Hardware" / "Alternati
    ves."), and cut by it on the rebuild alone, one crop took in a line
    the other did not. What either loses between the first and the last
    text still counts - every word between them is in the crop.
    """
    src_doc, out_doc = fitz.open(source_pdf), fitz.open(rebuilt_pdf)
    on_source = [t for t in texts if src_doc[source_page].search_for(t)]
    out_page = max(range(len(out_doc)),
                   key=lambda i: sum(bool(out_doc[i].search_for(t)) for t in on_source))
    shared = [t for t in on_source if out_doc[out_page].search_for(t)]
    src_doc.close()
    out_doc.close()
    return (out_page,
            _contents_rect(fitz, source_pdf, source_page, shared),
            _contents_rect(fitz, rebuilt_pdf, out_page, shared))


@pytest.mark.parametrize(
    "fixture_path, source_page",
    [
        (TOC_A, 0),
        (TOC_B, 0),
        (TOC_C, 0),
        (TOC_C, 1),
        (TOC_C, 2),
    ],
)
def test_toc_visual_overlay_matches_source(tmp_path, fixture_path, source_page):
    """Crop a source page's contents and the reassembled ones the same way,
    lay one ink matrix over the other, and fail if more than MAX_MISMATCH
    of the ink misses."""
    fitz = pytest.importorskip("pymupdf")
    pytest.importorskip("PIL")

    tocs = _extract_tocs(fixture_path)
    assert tocs, f"no table of contents extracted from {fixture_path.name}"
    texts = _page_texts(tocs, source_page)
    assert texts, f"no contents entries extracted from page {source_page + 1}"

    pdf_path = Path(_build_toc_pdf(tocs, str(tmp_path), "toc_overlay_doc"))

    out_page, src_rect, out_rect = _crop_rects(fitz, fixture_path, source_page, pdf_path, texts)
    assert src_rect is not None, "could not locate the source contents by their own text"
    assert out_rect is not None, "could not locate the assembled contents on their own page"

    img_source = _render_crop(fitz, fixture_path, source_page, src_rect)
    img_output = _render_crop(fitz, pdf_path, out_page, out_rect)

    mismatch = _mask_mismatch(img_source, img_output)
    assert mismatch <= MAX_MISMATCH, (
        f"{mismatch:.1%} of the ink misses between the source contents and the "
        f"reassembled ones (limit {MAX_MISMATCH:.0%}) - overlaid, they do not "
        f"line up: the rebuild is not reproducing the source page's layout"
    )
