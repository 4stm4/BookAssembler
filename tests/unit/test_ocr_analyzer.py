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
    from src.analyzers.ocr import analyzer as mod
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


class TestMeasuredParameters:
    """Values set from a timing run, not from intuition.

    Measured on a scanned Intel-3212 page against Qwen2.5-VL:
    512px answered in 24.6s with a correct transcription, 700px and 900px did
    not answer within 150s and 180s. The limit is a cliff, so the defaults sit
    at the size that demonstrably works.
    """

    def test_page_size_stays_at_the_size_that_answers(self):
        from src.analyzers.ocr import analyzer as ocr
        assert ocr.OCR_MAX_DIM <= 512, (
            "raised above the only size measured to answer; 700px timed out"
        )

    def test_timeout_leaves_room_over_the_observed_cost(self):
        from src.analyzers.ocr import analyzer as ocr
        assert ocr.OCR_TIMEOUT >= 100, (
            "24.6s was one page of ~1100 characters; a denser page needs more"
        )

    def test_ocr_timeout_exceeds_the_classification_one(self):
        """OCR generates a page of text; classification generates a word."""
        from src.agents import router
        from src.analyzers.ocr import analyzer as ocr
        assert ocr.OCR_TIMEOUT > router.INFER_TIMEOUT

    def test_timeouts_are_not_retried(self):
        from src.analyzers.ocr import analyzer as ocr
        assert ocr.OCR_ATTEMPTS == 1, (
            "a timeout means the page is too heavy, so a retry costs minutes "
            "and changes nothing"
        )

    def test_ocr_page_passes_its_own_budget_to_the_agent(self, monkeypatch, tmp_path):
        """The real _ocr_page, not a stub of it."""
        fitz = pytest.importorskip("pymupdf")
        from src.analyzers.ocr import analyzer as ocr

        pdf = tmp_path / "s.pdf"
        d = fitz.open(); d.new_page(); pdf.write_bytes(d.tobytes()); d.close()

        seen = {}

        def fake_call(host, task, png, prompt=None, kind=None, model=None,
                      timeout=None, attempts=None):
            seen.update(timeout=timeout, attempts=attempts, task=task)
            return "recovered"

        monkeypatch.setattr(ocr, "call_infer", fake_call)
        out = ocr.OCRAnalyzer()._ocr_page(str(pdf), 0, "http://a", "multimodel", None)

        assert out == "recovered"
        assert seen["timeout"] == ocr.OCR_TIMEOUT
        assert seen["attempts"] == ocr.OCR_ATTEMPTS


# --- per-line geometry and font (RFC 0021 §5.4) -----------------------------
# Before this, every recovered line shared the page box and carried no style,
# so a scanned page rendered as a stack of serif lines at the top left.

from src.analyzers.ocr.rules import _parse_ocr, _rect_from, _style_from
from src.krm.models import NormalizedRect

PAGE = NormalizedRect(0.0, 0.0, 1.0, 1.0)


def test_parse_ocr_reads_box_and_font_per_line():
    answer = (
        '{"text": "UNIVERSITY OF DUBLIN", "bbox": [300, 180, 700, 220], '
        '"font": "mono", "bold": false}\n'
        '{"text": "ANNUAL REPORT 1979/80", "bbox": [280, 730, 730, 770], '
        '"font": "mono", "bold": true}'
    )
    lines = _parse_ocr(answer, PAGE)
    assert [t for t, _, _ in lines] == [
        "UNIVERSITY OF DUBLIN", "ANNUAL REPORT 1979/80",
    ]
    # The two lines must land far apart vertically, not stacked.
    assert lines[0][1].y0 == pytest.approx(0.18)
    assert lines[1][1].y0 == pytest.approx(0.73)
    assert lines[1][2].is_monospace and lines[1][2].is_bold


def test_parse_ocr_falls_back_to_plain_text():
    """The model may ignore the format; the page must still transcribe."""
    lines = _parse_ocr("first line\nsecond line", PAGE)
    assert [t for t, _, _ in lines] == ["first line", "second line"]
    assert all(rect is None for _, rect, _ in lines)


def test_parse_ocr_accepts_a_json_array_in_a_fence():
    answer = '```json\n[{"text": "A", "bbox": [0, 0, 100, 50]}]\n```'
    assert [t for t, _, _ in _parse_ocr(answer, PAGE)] == ["A"]


def test_rect_is_repaired_not_propagated():
    """RFC 0002 §inv3: a model box may be inverted or past the edge."""
    r = _rect_from([900, 400, 100, 200], PAGE)
    assert (r.x0, r.x1) == (0.1, 0.9) and (r.y0, r.y1) == (0.2, 0.4)
    assert _rect_from([0, 0, 1400, 1400], PAGE) == NormalizedRect(0.0, 0.0, 1.0, 1.0)
    assert _rect_from("nonsense", PAGE) is None
    assert _rect_from([1, 2, 3], PAGE) is None


def test_rect_maps_into_the_placeholder_box():
    half = NormalizedRect(0.0, 0.5, 1.0, 1.0)
    r = _rect_from([0, 0, 1000, 1000], half)
    assert (r.y0, r.y1) == (0.5, 1.0)


def test_style_is_absent_when_nothing_was_observed():
    assert _style_from({"text": "x"}) is None
    assert _style_from({"font": "serif"}).font_family == "serif"
    assert _style_from({"bold": True}).is_bold


def test_ocr_sends_the_blocking_task_not_vision(monkeypatch, tmp_path):
    """RFC 0022 §4.5: OCR outranks page analysis, so it needs its own task.

    Both are served by the same model; only the class differs. Sending
    "vision" would put a page with no text at all behind page classification.
    """
    fitz = pytest.importorskip("pymupdf")
    from src.analyzers.ocr import analyzer as ocr
    from src.agents.tasks import MAX_PRIORITY, Priority

    pdf = tmp_path / "s.pdf"
    d = fitz.open(); d.new_page(); pdf.write_bytes(d.tobytes()); d.close()

    seen = {}
    monkeypatch.setattr(ocr, "call_infer",
                        lambda host, task, png, **kw: seen.update(task=task) or "x")
    ocr.OCRAnalyzer()._ocr_page(str(pdf), 0, "http://a", "multimodel", None)

    assert seen["task"] == "ocr"
    assert MAX_PRIORITY["ocr"] == Priority.BLOCKING
