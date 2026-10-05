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
contents' own extent, and one ink matrix is laid over the other. The limit is
test_visual_overlay's MAX_MISMATCH: one rule for every rebuilt region, a
table of contents gets no leniency a table does not.
"""

from pathlib import Path

import pytest

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument, TocEntryBlock
from tests.e2e.test_visual_overlay import MAX_MISMATCH, _mask_mismatch, _render_crop

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "toc"
TOC_A = FIXTURES / "toc_a.pdf"   # Intel "Contents": numbered entries, linked titles
TOC_B = FIXTURES / "toc_b.pdf"   # typewritten CONTENTS: sections, sub-entries, appendices
TOC_C = FIXTURES / "toc_c.pdf"   # "TABLE OF CONTENTS" over 3 pages: chapters, pages, descriptions

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
        fh.write(build_latex(doc))
    try:
        return compile_xelatex(f"{name}.tex", work_dir)
    except RuntimeError as exc:
        if "not found" in str(exc):
            pytest.skip(
                "local TeX Live is missing a package the preamble needs "
                f"(RFC 0021 SS4) - {exc}"
            )
        raise


def _contents_rect(fitz, pdf_path: Path, page_index: int, texts: list):
    """Locate one source page's contents on a page by their own text - the
    same way on the source page and on the assembled one.

    Top to bottom they run from the first of the texts found to the last,
    each looked for below the one before it: a title the list repeats
    ("Section") is the next one down, and a rebuilt page that runs on into
    the next source page's entries is cut where this page's end. Across,
    they take in every word printed between - a page number set off across
    a leader, a title the analyzer did not read, a description the rebuild
    dropped.
    """
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    found, below = [], float("-inf")
    for t in texts:
        hits = sorted(page.search_for(t), key=lambda r: (r.y0, r.x0))
        hit = next((r for r in hits if r.y0 > below), None)
        if hit is not None:
            found.append(hit)
            # The next text stands on a later row: below this one's middle.
            below = (hit.y0 + hit.y1) / 2
    if not found:
        doc.close()
        return None
    top, bottom = min(r.y0 for r in found), max(r.y1 for r in found)
    inside = found + [fitz.Rect(w[:4]) for w in page.get_text("words")
                      if top <= (w[1] + w[3]) / 2 <= bottom]
    doc.close()
    return fitz.Rect(min(r.x0 for r in inside), top, max(r.x1 for r in inside), bottom)


def _crop_rects(fitz, source_pdf: Path, source_page: int, rebuilt_pdf: Path, texts: list):
    """Where to cut the source page's contents and the rebuilt ones: both by
    _contents_rect from the same texts, on the source page and on the
    rebuilt page holding most of them - the rebuild breaks its pages where
    its own type runs out, not where the source's did. Returns the rebuilt
    page's index with the two rects.

    Unlike test_visual_overlay, the texts are not narrowed to those found
    on both pages: a description the rebuild does not print would then be
    cut from the source crop too, and cost nothing.
    """
    out_doc = fitz.open(rebuilt_pdf)
    out_page = max(range(len(out_doc)),
                   key=lambda i: sum(bool(out_doc[i].search_for(t)) for t in texts))
    out_doc.close()
    return (out_page,
            _contents_rect(fitz, source_pdf, source_page, texts),
            _contents_rect(fitz, rebuilt_pdf, out_page, texts))


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
    of the pixels disagree."""
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
        f"{mismatch:.1%} of pixels disagree between the source contents and the "
        f"reassembled ones (limit {MAX_MISMATCH:.0%}) - overlaid, they do not "
        f"line up: the rebuild is not reproducing the source page's layout"
    )
