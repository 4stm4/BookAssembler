"""Runner-side source fetching (RFC 0022 §4.2).

The Runner fetches and renders the page itself so the caller does not have to
push pixels up a thin uplink. The document is cached per URL, and a URL that
arrives over the network must not be usable to read local files or reach hosts
inside the Runner's network.
"""
import os

import pytest

from src.agents.runner import source_fetch as sf


@pytest.fixture(autouse=True)
def _tmp_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(sf, "CACHE_DIR", str(tmp_path / "cache"))
    sf._locks.clear()


class _Resp:
    def __init__(self, data):
        self._d = data
        self._pos = 0

    def read(self, n=-1):
        if self._pos >= len(self._d):
            return b""
        chunk = self._d[self._pos:] if n < 0 else self._d[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestUrlGuard:
    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.org/book.pdf",
        "gopher://example.org/book.pdf",
    ])
    def test_non_http_scheme_refused(self, url):
        with pytest.raises(sf.SourceFetchError):
            sf.fetch(url)

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/book.pdf",
        "http://10.0.0.5/book.pdf",
        "http://192.168.1.9/book.pdf",
        "http://169.254.169.254/latest/meta-data",
    ])
    def test_private_and_loopback_addresses_refused(self, url):
        """A caller must not be able to make the Runner read its own network."""
        with pytest.raises(sf.SourceFetchError):
            sf.fetch(url)

    def test_public_hostname_allowed(self, monkeypatch):
        monkeypatch.setattr(sf.urllib.request, "urlopen",
                            lambda *a, **k: _Resp(b"%PDF-1.4 body"))
        path = sf.fetch("https://archive.org/book.pdf")
        assert os.path.exists(path)


class TestCaching:
    def test_downloads_once_per_url(self, monkeypatch):
        calls = []

        def fake(*a, **k):
            calls.append(1)
            return _Resp(b"%PDF-1.4 body")

        monkeypatch.setattr(sf.urllib.request, "urlopen", fake)
        a = sf.fetch("https://example.org/book.pdf")
        b = sf.fetch("https://example.org/book.pdf")
        assert a == b
        assert len(calls) == 1, "a book was downloaded again for a second page"

    def test_distinct_urls_are_distinct_files(self, monkeypatch):
        monkeypatch.setattr(sf.urllib.request, "urlopen",
                            lambda *a, **k: _Resp(b"%PDF-1.4 body"))
        a = sf.fetch("https://example.org/one.pdf")
        b = sf.fetch("https://example.org/two.pdf")
        assert a != b

    def test_oversized_download_is_refused_and_leaves_no_file(self, monkeypatch):
        monkeypatch.setattr(sf, "MAX_BYTES", 10)
        monkeypatch.setattr(sf.urllib.request, "urlopen",
                            lambda *a, **k: _Resp(b"x" * 100))
        with pytest.raises(sf.SourceFetchError):
            sf.fetch("https://example.org/huge.pdf")
        assert not os.path.exists(sf._cache_path("https://example.org/huge.pdf"))

    def test_failed_download_leaves_no_partial_file(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("connection reset")

        monkeypatch.setattr(sf.urllib.request, "urlopen", boom)
        with pytest.raises(sf.SourceFetchError):
            sf.fetch("https://example.org/gone.pdf")
        assert not os.path.exists(sf._cache_path("https://example.org/gone.pdf"))


class TestRender:
    def _pdf_bytes(self):
        fitz = pytest.importorskip("pymupdf")
        doc = fitz.open()
        for n in range(3):
            doc.new_page().insert_text((72, 120), f"page {n}")
        data = doc.tobytes()
        doc.close()
        return data

    def test_renders_the_requested_page(self, monkeypatch):
        monkeypatch.setattr(sf.urllib.request, "urlopen",
                            lambda *a, **k: _Resp(self._pdf_bytes()))
        png = sf.render_page("https://example.org/b.pdf", 1)
        assert png.startswith(b"\x89PNG")

    def test_page_out_of_range_is_reported(self, monkeypatch):
        monkeypatch.setattr(sf.urllib.request, "urlopen",
                            lambda *a, **k: _Resp(self._pdf_bytes()))
        with pytest.raises(sf.SourceFetchError, match="out of range"):
            sf.render_page("https://example.org/b.pdf", 99)
