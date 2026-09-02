"""Sending a source reference instead of a rendered page.

Measured on this deployment rpi5 uploads at ~1.7 KB/s and downloads at
~4.6 MB/s. Pushing a rendered page costs ~13s against 1-3s of inference, so an
agent that can fetch the document itself is asked for that instead: a few
hundred bytes leave rpi5 and the document travels over the runner's own link.
"""
import json

import pytest

from src.agents import router


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    router._NO_SOURCE_FETCH.clear()
    monkeypatch.setattr(router.time, "sleep", lambda s: None)


def _agents(monkeypatch, source_fetch):
    monkeypatch.setattr(router, "load_agents", lambda: [
        {"host": "http://agent", "kind": "multimodel", "source_fetch": source_fetch},
    ])


def _capture(monkeypatch, handler):
    sent = []

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data.decode())
        sent.append(body)
        return handler(body)

    monkeypatch.setattr(router.urllib.request, "urlopen", fake_urlopen)
    return sent


class TestReferenceMode:
    def test_sends_reference_not_image(self, monkeypatch):
        _agents(monkeypatch, True)
        sent = _capture(monkeypatch,
                        lambda b: _Resp(json.dumps({"text": "ok"}).encode()))
        out = router.call_infer(
            "http://agent", "vision", b"IMAGEBYTES",
            source_url="https://example.org/book.pdf", page=3,
        )
        assert out == "ok"
        assert sent[0]["source_url"] == "https://example.org/book.pdf"
        assert sent[0]["page"] == 3
        assert "image_b64" not in sent[0], "the image was uploaded anyway"

    def test_payload_is_far_smaller_than_the_image(self, monkeypatch):
        _agents(monkeypatch, True)
        sent = _capture(monkeypatch,
                        lambda b: _Resp(json.dumps({"text": "ok"}).encode()))
        router.call_infer(
            "http://agent", "vision", b"X" * 22_000,
            source_url="https://example.org/book.pdf", page=1,
        )
        assert len(json.dumps(sent[0])) < 500

    def test_disabled_agent_uploads_the_image(self, monkeypatch):
        _agents(monkeypatch, False)
        sent = _capture(monkeypatch,
                        lambda b: _Resp(json.dumps({"text": "ok"}).encode()))
        router.call_infer(
            "http://agent", "vision", b"IMAGEBYTES",
            source_url="https://example.org/book.pdf", page=3,
        )
        assert "image_b64" in sent[0]
        assert "source_url" not in sent[0]

    def test_no_url_uploads_the_image(self, monkeypatch):
        _agents(monkeypatch, True)
        sent = _capture(monkeypatch,
                        lambda b: _Resp(json.dumps({"text": "ok"}).encode()))
        router.call_infer("http://agent", "vision", b"IMAGEBYTES")
        assert "image_b64" in sent[0]


class TestFallback:
    def test_runner_that_rejects_reference_gets_the_image(self, monkeypatch):
        """Deployable before the runner supports it: the page still gets done."""
        import urllib.error
        _agents(monkeypatch, True)

        def handler(body):
            if "source_url" in body:
                raise urllib.error.HTTPError(
                    "http://agent/infer", 422, "Unprocessable", {}, None)
            return _Resp(json.dumps({"text": "from-image"}).encode())

        sent = _capture(monkeypatch, handler)
        out = router.call_infer(
            "http://agent", "vision", b"IMAGEBYTES",
            source_url="https://example.org/book.pdf", page=2,
        )
        assert out == "from-image"
        assert "source_url" in sent[0] and "image_b64" in sent[1]

    def test_refusal_is_remembered_for_the_rest_of_the_book(self, monkeypatch):
        import urllib.error
        _agents(monkeypatch, True)

        def handler(body):
            if "source_url" in body:
                raise urllib.error.HTTPError(
                    "http://agent/infer", 422, "Unprocessable", {}, None)
            return _Resp(json.dumps({"text": "img"}).encode())

        sent = _capture(monkeypatch, handler)
        for page in range(3):
            router.call_infer("http://agent", "vision", b"IMG",
                              source_url="https://e.org/b.pdf", page=page)
        refs = [b for b in sent if "source_url" in b]
        assert len(refs) == 1, "kept re-probing a runner that cannot do it"

    def test_timeout_does_not_disable_reference_mode(self, monkeypatch):
        """A timeout says something about the link, not about the feature."""
        import socket
        _agents(monkeypatch, True)

        def handler(body):
            raise socket.timeout("timed out")

        _capture(monkeypatch, handler)
        router.call_infer("http://agent", "vision", b"IMG",
                          source_url="https://e.org/b.pdf", page=0)
        assert "http://agent" not in router._NO_SOURCE_FETCH


class TestSourceUrlLookup:
    def test_local_handles_are_not_sent_as_urls(self):
        from src.analyzers.page_agent import _source_url
        from src.krm.models import KnowledgeDocument
        for uri in ("upload://book.pdf", "sep://prov/book.pdf", "", None):
            doc = KnowledgeDocument(title="t")
            doc.metadata = {"source_url": uri} if uri else {}
            assert _source_url(doc) is None

    def test_http_url_is_used(self):
        from src.analyzers.page_agent import _source_url
        from src.krm.models import KnowledgeDocument
        doc = KnowledgeDocument(title="t")
        doc.metadata = {"source_url": "https://archive.org/book.pdf"}
        assert _source_url(doc) == "https://archive.org/book.pdf"
