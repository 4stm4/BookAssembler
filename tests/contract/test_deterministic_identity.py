"""RFC 0009 §5.2 / 0001 §2.3: node identity is derived, so re-runs match."""
import io

import pytest

from src.krm.identity import (
    derive_composite_id,
    derive_id,
    derive_source_id,
    is_derived,
)
from src.krm.models import NormalizedRect


class _BBox(NormalizedRect):
    pass


def _rect(y0=0.1):
    return NormalizedRect(0.1, y0, 0.9, y0 + 0.05)


class TestDeriveId:
    def test_same_inputs_same_id(self):
        a = derive_source_id("paragraph", "file://b.pdf", 3, _rect(), "hello")
        b = derive_source_id("paragraph", "file://b.pdf", 3, _rect(), "hello")
        assert a == b

    def test_text_change_changes_id(self):
        a = derive_source_id("paragraph", "file://b.pdf", 3, _rect(), "hello")
        b = derive_source_id("paragraph", "file://b.pdf", 3, _rect(), "goodbye")
        assert a != b

    def test_position_change_changes_id(self):
        a = derive_source_id("paragraph", "file://b.pdf", 3, _rect(0.1), "hello")
        b = derive_source_id("paragraph", "file://b.pdf", 3, _rect(0.5), "hello")
        assert a != b

    def test_page_change_changes_id(self):
        a = derive_source_id("paragraph", "file://b.pdf", 3, _rect(), "x")
        b = derive_source_id("paragraph", "file://b.pdf", 4, _rect(), "x")
        assert a != b

    def test_source_change_changes_id(self):
        a = derive_source_id("paragraph", "file://a.pdf", 1, _rect(), "x")
        b = derive_source_id("paragraph", "file://b.pdf", 1, _rect(), "x")
        assert a != b

    def test_kind_separates_colocated_nodes(self):
        """A heading promoted from a paragraph shares bbox and text."""
        p = derive_source_id("paragraph", "file://b.pdf", 1, _rect(), "Title")
        h = derive_source_id("heading", "file://b.pdf", 1, _rect(), "Title")
        assert p != h

    def test_ordinal_disambiguates_identical_nodes(self):
        a = derive_source_id("paragraph", "f", 1, _rect(), "same", ordinal=0)
        b = derive_source_id("paragraph", "f", 1, _rect(), "same", ordinal=1)
        assert a != b

    def test_ids_are_uuid5(self):
        assert is_derived(derive_id("x", "y"))

    def test_random_uuid_is_not_derived(self):
        from uuid import uuid4
        assert not is_derived(str(uuid4()))

    def test_is_derived_rejects_garbage(self):
        assert not is_derived("not-a-uuid")
        assert not is_derived("")
        assert not is_derived(None)


class TestCompositeId:
    def test_stable_for_same_children(self):
        assert derive_composite_id("table", "a", "b") == \
               derive_composite_id("table", "a", "b")

    def test_order_independent(self):
        """Detectors must not produce a different table id per visit order."""
        assert derive_composite_id("table", "a", "b", "c") == \
               derive_composite_id("table", "c", "a", "b")

    def test_different_children_differ(self):
        assert derive_composite_id("table", "a", "b") != \
               derive_composite_id("table", "a", "c")

    def test_kind_separates(self):
        assert derive_composite_id("table", "a") != \
               derive_composite_id("list", "a")


class TestAdapterReExtraction:
    """The point of all this: parsing the same PDF twice yields the same ids."""

    def _tiny_pdf(self) -> bytes:
        fitz = pytest.importorskip("pymupdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 200), "Deterministic identity check")
        data = doc.tobytes()
        doc.close()
        return data

    def _parse(self, raw: bytes):
        from src.adapters.pdf_adapter import PdfSourceAdapter
        stream = io.BytesIO(raw)
        return PdfSourceAdapter().parse(stream, "file://fixed.pdf")

    def _ids(self, doc):
        out = []

        def walk(n):
            out.append(n.id)
            for c in getattr(n, "children", []) or []:
                walk(c)

        for c in doc.root_containers:
            walk(c)
        return out

    def test_two_parses_produce_identical_ids(self):
        raw = self._tiny_pdf()
        first = self._ids(self._parse(raw))
        second = self._ids(self._parse(raw))
        assert first == second
        assert len(first) > 1

    def test_parsed_ids_are_derived_not_random(self):
        raw = self._tiny_pdf()
        ids = self._ids(self._parse(raw))
        assert all(is_derived(i) for i in ids), \
            "every adapter-created node must carry a derived id"
