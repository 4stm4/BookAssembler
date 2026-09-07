"""src/analyzers/source_io.py — resolving the source file and encoding pages.

Both functions lived in page_agent before this, reached into by ocr and
api/app.py as a hidden dependency; ocr even carried a same-named wrapper that
did nothing but that import. Neither had a direct test — only indirect
coverage through whichever analyzer happened to call them via monkeypatch.
"""

import os

import pytest

from src.analyzers.source_io import pixmap_to_jpeg, resolve_source_path
from src.krm.models import KnowledgeDocument


def _doc(uri: str) -> KnowledgeDocument:
    return KnowledgeDocument(id="d", source_uri=uri)


class TestResolveSourcePath:
    def test_file_uri_that_exists(self, tmp_path):
        pdf = tmp_path / "book.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        assert resolve_source_path(_doc(f"file://{pdf}")) == str(pdf)

    def test_file_uri_that_does_not_exist(self):
        assert resolve_source_path(_doc("file:///nowhere/book.pdf")) is None

    def test_upload_uri_found_under_ssd_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAE_SSD_PATH", str(tmp_path))
        job_dir = tmp_path / "job-123"
        job_dir.mkdir()
        (job_dir / "book.pdf").write_bytes(b"%PDF-1.4")
        assert resolve_source_path(_doc("upload://book.pdf")) == str(
            job_dir / "book.pdf")

    def test_upload_uri_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAE_SSD_PATH", str(tmp_path))
        assert resolve_source_path(_doc("upload://missing.pdf")) is None

    def test_sep_uri_found_under_ssd_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAE_SSD_PATH", str(tmp_path))
        (tmp_path / "books").mkdir()
        (tmp_path / "books" / "a.pdf").write_bytes(b"%PDF-1.4")
        assert resolve_source_path(_doc("sep://provider/books/a.pdf")) == str(
            tmp_path / "books" / "a.pdf")

    def test_sep_uri_malformed_without_a_relative_part(self):
        assert resolve_source_path(_doc("sep://provider-only")) is None

    def test_absolute_path_that_exists(self, tmp_path):
        pdf = tmp_path / "book.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        assert resolve_source_path(_doc(str(pdf))) == str(pdf)

    def test_relative_or_unknown_scheme_resolves_to_none(self):
        assert resolve_source_path(_doc("relative/path.pdf")) is None
        assert resolve_source_path(_doc("")) is None


class TestPixmapToJpeg:
    class _FakePixmap:
        def __init__(self, w, h):
            self.width, self.height = w, h
            self.samples = bytes([128, 64, 32] * (w * h))

    def test_output_is_a_valid_jpeg(self):
        from PIL import Image
        import io
        data = pixmap_to_jpeg(self._FakePixmap(16, 16))
        img = Image.open(io.BytesIO(data))
        assert img.format == "JPEG"

    def test_oversized_page_is_downscaled_to_max_dim(self):
        from PIL import Image
        import io
        data = pixmap_to_jpeg(self._FakePixmap(1000, 500), max_dim=100)
        img = Image.open(io.BytesIO(data))
        assert max(img.size) == 100

    def test_small_page_is_not_upscaled(self):
        from PIL import Image
        import io
        data = pixmap_to_jpeg(self._FakePixmap(50, 30), max_dim=512)
        img = Image.open(io.BytesIO(data))
        assert img.size == (50, 30)

    def test_quality_is_a_parameter_not_a_global(self):
        low = pixmap_to_jpeg(self._FakePixmap(64, 64), quality=10)
        high = pixmap_to_jpeg(self._FakePixmap(64, 64), quality=95)
        assert len(high) > len(low)
