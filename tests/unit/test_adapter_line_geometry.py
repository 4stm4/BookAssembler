"""The adapter keeps each source line's geometry (RFC 0021 §3, §5.4).

A PDF text block can cover several laid-out lines — a contents entry is
"Section 2" on the left and "Machine Utilisation" on the right. Collapsing them
into one span leaves a single bbox for the lot, and the page can no longer be
rebuilt: the two columns come back as one run-on paragraph.
"""
import io

import pytest

from src.adapters.pdf_adapter import PdfSourceAdapter


def _pdf_two_column_toc() -> bytes:
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    page = doc.new_page()
    # Left column: labels. Right column: titles, well clear of them.
    page.insert_text((72, 120), "Section 1")
    page.insert_text((300, 120), "Introduction")
    page.insert_text((72, 150), "Section 2")
    page.insert_text((300, 150), "Machine Utilisation")
    data = doc.tobytes()
    doc.close()
    return data


def _parse(raw: bytes):
    return PdfSourceAdapter().parse(io.BytesIO(raw), "file://toc.pdf")


def _blocks(doc):
    return [c for c in doc.root_containers[0].children
            if getattr(c, "inlines", None)]


def _text(node) -> str:
    return " ".join(
        s.text for i in (node.inlines or []) for s in getattr(i, "spans", [])
    ).strip()


class TestLineGeometry:
    def test_lines_keep_separate_bboxes(self):
        doc = _parse(_pdf_two_column_toc())
        multi = [b for b in _blocks(doc) if len(b.inlines) > 1]
        assert multi, "every block collapsed to a single inline"
        for b in multi:
            boxes = [
                i.visual_layout.bounding_box
                for i in b.inlines
                if getattr(i, "visual_layout", None)
            ]
            assert len(boxes) == len(b.inlines), "an inline lost its geometry"
            assert len({(round(x.x0, 4), round(x.y0, 4)) for x in boxes}) > 1, \
                "all inlines share one position"

    def test_left_and_right_column_are_distinguishable(self):
        """The whole point: x tells the label apart from the title."""
        doc = _parse(_pdf_two_column_toc())
        xs = [
            i.visual_layout.bounding_box.x0
            for b in _blocks(doc) for i in b.inlines
            if getattr(i, "visual_layout", None)
        ]
        assert max(xs) - min(xs) > 0.2, "columns are not separated in x"

    def test_each_line_carries_style(self):
        doc = _parse(_pdf_two_column_toc())
        for b in _blocks(doc):
            for i in b.inlines:
                vl = getattr(i, "visual_layout", None)
                if vl:
                    assert vl.style is not None
                    assert vl.style.font_size_pt > 0

    def test_block_text_is_unchanged(self):
        """Splitting inlines must not alter what the block says."""
        doc = _parse(_pdf_two_column_toc())
        joined = " ".join(_text(b) for b in _blocks(doc))
        for expected in ("Section 1", "Introduction",
                         "Section 2", "Machine Utilisation"):
            assert expected in joined

    def test_bboxes_stay_inside_the_page(self):
        doc = _parse(_pdf_two_column_toc())
        for b in _blocks(doc):
            for i in b.inlines:
                vl = getattr(i, "visual_layout", None)
                if not vl:
                    continue
                bb = vl.bounding_box
                assert 0.0 <= bb.x0 <= bb.x1 <= 1.0
                assert 0.0 <= bb.y0 <= bb.y1 <= 1.0

    def test_identity_still_deterministic(self):
        """Per-line inlines must not disturb derived ids (RFC 0009 §5.2)."""
        raw = _pdf_two_column_toc()
        a = [b.id for b in _blocks(_parse(raw))]
        b = [b.id for b in _blocks(_parse(raw))]
        assert a == b and a
