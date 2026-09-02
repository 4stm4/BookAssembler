"""OCRAnalyzer recovers text from pages with no text layer (RFC 0008 §75).

The adapter flags those pages and emits an empty placeholder. Before this
analyzer the flag was written and never read: on /data/kae/books that is 238 of
1738 pages and 19 documents that are scans end to end, all of which left the
pipeline empty.
"""
import pytest

from src.analyzers.ocr import OCRAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    VisualLayout,
)


def _placeholder(page=0):
    b = ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text="")])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
            page_or_screen_index=page,
        ),
    )
    b.metadata = {"needs_ocr": True}
    return b


def _doc(children):
    c = ContainerUnit(title="ch", children=list(children))
    return KnowledgeDocument(title="T", source_uri="file://scan.pdf",
                             root_containers=[c]), c


def _text(node):
    return " ".join(
        s.text for i in (getattr(node, "inlines", None) or [])
        for s in getattr(i, "spans", [])
    ).strip()


@pytest.fixture
def wired(monkeypatch, tmp_path):
    from src.analyzers import ocr as mod
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(mod, "pick", lambda role: ("http://agent", "m", "multimodel"))
    monkeypatch.setattr(mod, "_resolve_source_path", lambda doc: str(pdf))
    return mod


class TestRecovery:
    def test_placeholder_is_replaced_by_recovered_lines(self, wired, monkeypatch):
        monkeypatch.setattr(wired.OCRAnalyzer, "_ocr_page",
                            lambda self, *a, **k: "INTEL 3212\nMULTI-MODE LATCH\nPin 1")
        doc, c = _doc([_placeholder(0)])
        wired.OCRAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

        alive = [n for n in c.children if not n.is_tombstoned]
        assert [_text(n) for n in alive] == [
            "INTEL 3212", "MULTI-MODE LATCH", "Pin 1",
        ]

    def test_placeholder_is_tombstoned_not_deleted(self, wired, monkeypatch):
        """RFC 0001 §2.4 — the original stays, marked as replaced."""
        monkeypatch.setattr(wired.OCRAnalyzer, "_ocr_page",
                            lambda self, *a, **k: "recovered")
        doc, c = _doc([_placeholder(0)])
        wired.OCRAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

        dead = [n for n in c.children if n.is_tombstoned]
        assert len(dead) == 1
        assert dead[0].metadata["tombstone_reason"] == "replaced_by_ocr"
        assert "needs_ocr" not in dead[0].metadata

    def test_recovered_lines_keep_the_page(self, wired, monkeypatch):
        monkeypatch.setattr(wired.OCRAnalyzer, "_ocr_page",
                            lambda self, *a, **k: "a\nb")
        doc, c = _doc([_placeholder(7)])
        wired.OCRAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        alive = [n for n in c.children if not n.is_tombstoned]
        assert {n.visual_layout.page_or_screen_index for n in alive} == {7}

    def test_ids_are_deterministic(self, wired, monkeypatch):
        """RFC 0009 §5.2 — a second run of the same scan gives the same ids."""
        monkeypatch.setattr(wired.OCRAnalyzer, "_ocr_page",
                            lambda self, *a, **k: "one\ntwo")
        ids = []
        for _ in range(2):
            doc, c = _doc([_placeholder(3)])
            wired.OCRAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
            ids.append([n.id for n in c.children if not n.is_tombstoned])
        assert ids[0] == ids[1] and ids[0]

    def test_repeated_lines_get_distinct_ids(self, wired, monkeypatch):
        """A scan may legitimately repeat a line; they must not collide."""
        monkeypatch.setattr(wired.OCRAnalyzer, "_ocr_page",
                            lambda self, *a, **k: "VCC\nVCC\nVCC")
        doc, c = _doc([_placeholder(0)])
        wired.OCRAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        alive = [n for n in c.children if not n.is_tombstoned]
        assert len({n.id for n in alive}) == 3


class TestDegradation:
    def test_no_vision_agent_leaves_the_flag(self, wired, monkeypatch):
        """Nothing to fall back on, so the page stays flagged for a later run."""
        monkeypatch.setattr(wired, "pick", lambda role: (None, None, ""))
        doc, c = _doc([_placeholder(0)])
        wired.OCRAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert c.children[0].metadata["needs_ocr"] is True
        assert not c.children[0].is_tombstoned

    def test_empty_reply_leaves_the_page_alone(self, wired, monkeypatch):
        monkeypatch.setattr(wired.OCRAnalyzer, "_ocr_page",
                            lambda self, *a, **k: "   \n  \n")
        doc, c = _doc([_placeholder(0)])
        wired.OCRAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert not c.children[0].is_tombstoned

    def test_pages_without_the_flag_are_untouched(self, wired, monkeypatch):
        monkeypatch.setattr(wired.OCRAnalyzer, "_ocr_page",
                            lambda self, *a, **k: "should not be called")
        normal = ParagraphBlock(
            inlines=[TextLineInline(spans=[StyledTextSpan(text="real text")])],
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.1, 0.1, 0.9, 0.2),
                page_or_screen_index=0),
        )
        doc, c = _doc([normal])
        wired.OCRAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert _text(c.children[0]) == "real text"
        assert len(c.children) == 1

    def test_a_dead_agent_stops_the_run(self, wired, monkeypatch):
        calls = []

        def boom(self, *a, **k):
            calls.append(1)
            raise RuntimeError("agent down")

        monkeypatch.setattr(wired.OCRAnalyzer, "_ocr_page", boom)
        doc, c = _doc([_placeholder(p) for p in range(30)])
        wired.OCRAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert len(calls) < 30, "kept asking a dead agent for every page"


class TestPipeline:
    def test_registered_before_the_detectors(self):
        """Everything downstream reads text, so OCR must precede it."""
        from src.analyzers import create_default_pipeline
        names = [type(a).__name__ for a in create_default_pipeline()]
        assert "OCRAnalyzer" in names
        assert names.index("OCRAnalyzer") < names.index("HeadingAnalyzer")
        assert names.index("OCRAnalyzer") < names.index("TableDetectorAnalyzer")
