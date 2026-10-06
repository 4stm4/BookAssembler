"""E2E: pixel-level visual assert between each paragraph of a source page
and the same paragraph as extracted + reassembled through the real
pipeline - the overlay check of test_visual_overlay.py and
test_toc_overlay.py, for paragraphs.

Each fixture page goes through the whole pipeline and is assembled page by
page, as the product assembles a book (translator, API). Every paragraph
the pipeline reads off the page (a live ParagraphBlock) is then cut out of
the source page and out of the rebuild the same way, and one ink matrix is
laid over the other.

A paragraph is located by its words, not its lines: the rebuild may break
its lines elsewhere, and a line of the source is no text of the rebuild.
On each page, the paragraph's run of words - matched as a sequence, so a
common word elsewhere on the page does not pull the crop there, and OCR's
misreadings do not break it - bounds the crop: from its first word's top
to its last word's baseline, across every word between. What the crop then
compares is how the paragraph lies - its lines, their breaks and spacing,
its type - against the print.

The measure is test_toc_overlay's: the share of the ink of either crop
with no ink of the other within a pixel (_mask_mismatch), a text located
by its ink (_ink_of). The limit is this file's own, 7% (MAX_MISMATCH).
"""

import difflib
import re
from pathlib import Path

import pytest

from src.assembler.latex_builder import build_latex, compile_xelatex
from src.krm.models import ContainerUnit, KnowledgeDocument, ParagraphBlock
from tests.e2e.test_toc_overlay import _ink_of, _mask_mismatch
from tests.e2e.test_visual_overlay import _render_crop

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "paragraph"
PARAGRAPH_A = FIXTURES / "paragraph_a.pdf"   # one justified paragraph, a bold run-in heading
PARAGRAPH_B = FIXTURES / "paragraph_b.pdf"   # headings, justified paragraphs, a short list
PARAGRAPH_C = FIXTURES / "paragraph_c.pdf"   # an instruction: formula line, paragraph, bit diagrams
PARAGRAPH_D = FIXTURES / "paragraph_d.pdf"   # two columns: overlined signals, subscripts, bold runs
PARAGRAPH_E = FIXTURES / "paragraph_e.pdf"   # two dense columns, a margin tab

# Share of the ink allowed to miss the other crop's ink, for every
# paragraph of every page alike.
MAX_MISMATCH = 0.07

# Of a paragraph's words, the share its run on a page must match to be
# found there at all; and how many page words may stand between two
# matched pieces of one run (an OCR misreading, a hyphenation).
_MIN_MATCHED = 0.5
_RUN_GAP = 6

_BASELINE_DENSITY = 0.3   # a row this dense against the line's densest is above its baseline
_BASELINE_FALL = 0.6      # the row under the baseline holds less than this of its ink


def _extract(pdf_path: Path) -> KnowledgeDocument:
    """The document the real pipeline reads off a PDF, every analyzer run."""
    from src.adapters.pdf_adapter import PdfSourceAdapter
    from src.analyzers import create_default_pipeline
    from src.analyzers.pipeline import PipelineRunner
    from src.graph.knowledge_graph import KnowledgeGraph
    from src.graph.reading_graph import ReadingGraph

    with open(pdf_path, "rb") as fh:
        doc = PdfSourceAdapter().parse(fh, f"file://{pdf_path}")
    PipelineRunner(create_default_pipeline()).execute(doc, ReadingGraph(), KnowledgeGraph())
    return doc


def _paragraphs(doc: KnowledgeDocument, page_index: int = 0) -> list:
    """The live paragraphs on one source page, in the document's order."""
    out = []

    def walk(node):
        if isinstance(node, ContainerUnit):
            for child in node.children:
                walk(child)
        elif type(node) is ParagraphBlock and not node.is_tombstoned:
            vl = node.visual_layout
            if vl is not None and vl.page_or_screen_index == page_index:
                out.append(node)

    for root in doc.root_containers:
        walk(root)
    return out


def _paragraph_text(paragraph: ParagraphBlock) -> str:
    return " ".join(
        span.text for inline in paragraph.inlines for span in getattr(inline, "spans", [])
        if hasattr(span, "text")
    )


def _build_pdf(doc: KnowledgeDocument, work_dir: str, name: str) -> str:
    import os
    tex_path = os.path.join(work_dir, f"{name}.tex")
    with open(tex_path, "w") as fh:
        # Page by page, as the product assembles a book.
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


def _tokens(words: list) -> list:
    """Words as compared: letters and figures only, lowercased, a word broken
    at a line's end by a hyphen joined to its rest. Each token keeps the
    words it was made of (their indices)."""
    out = []
    pending = None
    for k, word in enumerate(words):
        text = re.sub(r"[^\w-]", "", word).lower()
        if pending is not None:
            out.append((pending[0] + text.replace("-", ""), pending[1] + [k]))
            pending = None
            continue
        if text.endswith("-") and len(text) > 1:
            pending = (text[:-1], [k])
            continue
        text = text.replace("-", "")
        if text:
            out.append((text, [k]))
    if pending is not None:
        out.append(pending)
    return out


def _run_on_page(page, paragraph_words: list):
    """The page words a paragraph's run of words matches - indices into
    page.get_text("words") - or None where too little of it is found."""
    words = page.get_text("words")
    have = _tokens([w[4] for w in words])
    want = [t for t, _ in _tokens(paragraph_words)]
    if not have or not want:
        return None
    matcher = difflib.SequenceMatcher(None, [t for t, _ in have], want, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size]
    if not blocks:
        return None
    # The run grows from its longest matched piece over pieces close by on
    # the page and in order in the paragraph; a stray match elsewhere does
    # not join it.
    anchor = max(blocks, key=lambda b: b.size)
    run = [anchor]
    for b in sorted(blocks, key=lambda b: b.a):
        if b is anchor:
            continue
        first, last = run[0], run[-1]
        if b.a >= last.a + last.size and b.a - (last.a + last.size) <= _RUN_GAP and b.b >= last.b + last.size:
            run.append(b)
        elif b.a + b.size <= first.a and first.a - (b.a + b.size) <= _RUN_GAP and b.b + b.size <= first.b:
            run.insert(0, b)
    run.sort(key=lambda b: b.a)
    if sum(b.size for b in run) < _MIN_MATCHED * len(want):
        return None
    lo, hi = run[0].a, run[-1].a + run[-1].size - 1
    return [k for token in have[lo:hi + 1] for k in token[1]]


def _baseline_of(fitz, page, rect) -> float:
    """Where the ink at rect stands: down from its densest row, the first
    its ink falls away under by _BASELINE_FALL for good."""
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


def _paragraph_rect(fitz, page, run: list):
    """A paragraph's extent on a page, from its run of words: every word's
    ink (_ink_of), from the first word's top to the last word's baseline -
    how far a descender reaches is its face's."""
    words = page.get_text("words")
    inks = [_ink_of(fitz, page, fitz.Rect(words[k][:4])) for k in run]
    top = min(r.y0 for r in inks)
    last = inks[-1]
    bottom = _baseline_of(fitz, page, last)
    inside = [r for r in inks if (r.y0 + r.y1) / 2 <= bottom] or inks
    return fitz.Rect(min(r.x0 for r in inside), top, max(r.x1 for r in inside), max(bottom, top + 1))


def _crop_rects(fitz, source_pdf: Path, rebuilt_pdf: Path, paragraph: ParagraphBlock, source_page: int = 0):
    """Where to cut a paragraph on the source page and in the rebuild -
    both by the run of its words (_run_on_page), the rebuilt page being the
    one where the run is found best. Returns (rebuilt page index, source
    rect, rebuilt rect); a rect is None where the run is not found."""
    words = _paragraph_text(paragraph).split()
    src = fitz.open(source_pdf)[source_page]
    out_doc = fitz.open(rebuilt_pdf)
    src_run = _run_on_page(src, words)
    runs = [(i, _run_on_page(out_doc[i], words)) for i in range(len(out_doc))]
    found = [(i, r) for i, r in runs if r]
    out_page, out_run = max(found, key=lambda ir: len(ir[1])) if found else (0, None)
    return (
        out_page,
        _paragraph_rect(fitz, src, src_run) if src_run else None,
        _paragraph_rect(fitz, out_doc[out_page], out_run) if out_run else None,
    )


@pytest.mark.parametrize(
    "fixture_path",
    [PARAGRAPH_A, PARAGRAPH_B, PARAGRAPH_C, PARAGRAPH_D, PARAGRAPH_E],
)
def test_paragraph_visual_overlay_matches_source(tmp_path, fixture_path):
    """Crop every paragraph of the page out of the source and the
    reassembled page the same way, lay one ink matrix over the other, and
    fail if more than MAX_MISMATCH of any paragraph's ink misses."""
    fitz = pytest.importorskip("pymupdf")
    pytest.importorskip("PIL")

    doc = _extract(fixture_path)
    paragraphs = _paragraphs(doc)
    assert paragraphs, f"no paragraph extracted from {fixture_path.name}"

    pdf_path = Path(_build_pdf(doc, str(tmp_path), "paragraph_overlay_doc"))

    misses = []
    for k, paragraph in enumerate(paragraphs):
        out_page, src_rect, out_rect = _crop_rects(fitz, fixture_path, pdf_path, paragraph)
        label = f"paragraph {k + 1} ({_paragraph_text(paragraph)[:40]!r})"
        assert src_rect is not None, f"{label}: not found on the source page by its own words"
        assert out_rect is not None, f"{label}: not found in the assembled page by its own words"
        mismatch = _mask_mismatch(_render_crop(fitz, fixture_path, 0, src_rect),
                                  _render_crop(fitz, pdf_path, out_page, out_rect))
        if mismatch > MAX_MISMATCH:
            misses.append(f"{label}: {mismatch:.1%}")
    assert not misses, (
        f"{len(misses)} of {len(paragraphs)} paragraphs miss more than {MAX_MISMATCH:.0%} of their ink "
        f"against the source - overlaid, they do not line up: " + "; ".join(misses)
    )
