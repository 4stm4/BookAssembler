"""PageAgent persists the vision-derived page role so the assembler can use it."""
import pytest

from src.analyzers.page_agent import PageAgentAnalyzer
from src.krm.geometry import union_bbox as _union_bbox
from src.assembler.page_assembler import group_by_page
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


def _para(text: str, page: int = 0, y0: float = 0.1) -> ParagraphBlock:
    return ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(0.1, y0, 0.9, y0 + 0.05),
            page_or_screen_index=page,
        ),
    )


class TestApplyPageRole:
    def test_role_written_to_metadata(self):
        blocks = [(_para("a"), None), (_para("b"), None)]
        PageAgentAnalyzer()._apply_page_role(blocks, "toc")
        for b, _ in blocks:
            assert b.metadata["page_role"] == "toc"
            assert b.metadata["page_role_source"] == "PageAgent"

    def test_empty_role_is_not_written(self):
        blocks = [(_para("a"), None)]
        PageAgentAnalyzer()._apply_page_role(blocks, "")
        assert "page_role" not in (blocks[0][0].metadata or {})

    def test_role_is_deterministic(self):
        """RFC 0009: the marker must not carry a clock or a nonce."""
        b1 = [(_para("a"), None)]
        b2 = [(_para("a"), None)]
        PageAgentAnalyzer()._apply_page_role(b1, "toc")
        PageAgentAnalyzer()._apply_page_role(b2, "toc")
        assert b1[0][0].metadata == b2[0][0].metadata

    def test_assembler_picks_up_persisted_role(self):
        """End of the wire: PageAgent writes it, group_by_page reads it."""
        p = _para("Chapter 1 .... 7", page=4)
        PageAgentAnalyzer()._apply_page_role([(p, None)], "toc")

        doc = KnowledgeDocument(
            title="T", root_containers=[ContainerUnit(title="c", children=[p])]
        )
        pages = group_by_page(doc)
        assert pages[4].role == "toc"

    def test_non_positional_role_leaves_page_in_reflow(self):
        p = _para("body text", page=2)
        PageAgentAnalyzer()._apply_page_role([(p, None)], "text")

        doc = KnowledgeDocument(
            title="T", root_containers=[ContainerUnit(title="c", children=[p])]
        )
        pages = group_by_page(doc)
        assert pages[2].role == "text"


class TestTableGeometry:
    """RFC 0021 §5.4: a merged table must keep the region it actually covers."""

    def test_union_bbox_covers_all_blocks(self):
        nodes = [_para("a", y0=0.2), _para("b", y0=0.5)]
        bb = _union_bbox(nodes)
        assert bb.y0 == pytest.approx(0.2)
        assert bb.y1 == pytest.approx(0.55)
        assert bb.x0 == pytest.approx(0.1)
        assert bb.x1 == pytest.approx(0.9)

    def test_union_bbox_none_without_layout(self):
        assert _union_bbox([ParagraphBlock(inlines=[])]) is None

    def test_padding_is_clamped_to_unit_square(self):
        bb = _union_bbox([_para("a", y0=0.0)], pad=0.5)
        assert bb.x0 == 0.0 and bb.y0 == 0.0
        assert bb.x1 == 1.0 and bb.y1 <= 1.0

    def test_merged_table_is_not_full_page(self):
        parent = ContainerUnit(title="c", children=[])
        blocks = [(_para("a", y0=0.3), parent), (_para("b", y0=0.4), parent)]
        parent.children = [b for b, _ in blocks]

        PageAgentAnalyzer()._replace_with_table(blocks, "\\begin{tabular}{l}x\\end{tabular}", 0)

        table = next(c for c in parent.children if not isinstance(c, ParagraphBlock))
        bb = table.visual_layout.bounding_box
        assert (bb.x0, bb.y0, bb.x1, bb.y1) != (0.0, 0.0, 1.0, 1.0)
        assert bb.y0 == pytest.approx(0.3)
        assert bb.y1 == pytest.approx(0.45)


class _FakeAgent:
    """Records call order and returns a canned result per page."""

    def __init__(self, roles=None, fail_pages=(), delay=None):
        self.roles = roles or {}
        self.fail_pages = set(fail_pages)
        self.delay = delay or {}
        self.calls = []
        self.max_in_flight = 0
        self._in_flight = 0
        self._lock = __import__("threading").Lock()

    def __call__(self, pdf_path, page_index, host, blocks, kind=None, model=None):
        import time as _t
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
            self.calls.append(page_index)
        try:
            _t.sleep(self.delay.get(page_index, 0.02))
            if page_index in self.fail_pages:
                raise RuntimeError(f"page {page_index} boom")
            return (self.roles.get(page_index, "text"), {}, None)
        finally:
            with self._lock:
                self._in_flight -= 1


def _paged_doc(pages):
    """One container, `pages` -> number of paragraph blocks on that page."""
    children = []
    for pg, n in sorted(pages.items()):
        for i in range(n):
            children.append(_para(f"p{pg}-{i}", page=pg, y0=0.05 + i * 0.05))
    c = ContainerUnit(title="ch", children=children)
    return KnowledgeDocument(title="T", source_uri="file://x.pdf",
                             root_containers=[c]), c


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """PageAgent with a reachable vision agent and a resolvable source."""
    from src.analyzers import page_agent as pa

    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(pa, "pick", lambda role: ("http://agent", "m", "multimodel"))
    monkeypatch.setattr(pa, "_resolve_source_path", lambda doc: str(pdf))
    # No test should reach the real renderer; opt in by overriding this.
    monkeypatch.setattr(pa.PageAgentAnalyzer, "_recognize_table",
                        lambda self, *a, **k: None)
    return pa


class TestConcurrencyAndOrder:
    def test_requests_overlap(self, wired, monkeypatch):
        agent = _FakeAgent()
        monkeypatch.setattr(wired.PageAgentAnalyzer, "_classify_page",
                            lambda self, *a, **k: agent(*a, **k))
        doc, _c = _paged_doc({0: 6, 1: 6, 2: 6, 3: 6, 4: 6, 5: 6})
        wired.PageAgentAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert agent.max_in_flight > 1, "pages were fetched one at a time"

    def test_roles_applied_in_page_order_not_completion_order(self, wired, monkeypatch):
        """RFC 0009: KRM must not depend on which reply arrives first."""
        # Page 0 answers slowest, so completion order is the reverse of page order.
        agent = _FakeAgent(roles={0: "toc", 1: "table", 2: "figure"},
                           delay={0: 0.25, 1: 0.10, 2: 0.01})
        monkeypatch.setattr(wired.PageAgentAnalyzer, "_classify_page",
                            lambda self, *a, **k: agent(*a, **k))
        doc, c = _paged_doc({0: 6, 1: 6, 2: 6})
        wired.PageAgentAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())

        by_page = {}
        for ch in c.children:
            pg = ch.visual_layout.page_or_screen_index
            by_page.setdefault(pg, set()).add((ch.metadata or {}).get("page_role"))
        assert by_page[0] == {"toc"}
        assert by_page[1] == {"table"}
        assert by_page[2] == {"figure"}

    def test_result_is_stable_across_runs(self, wired, monkeypatch):
        roles = {0: "toc", 1: "table", 2: "figure", 3: "text"}
        seen = []
        for delays in ({0: 0.2, 3: 0.01}, {3: 0.2, 0: 0.01}):
            agent = _FakeAgent(roles=roles, delay=delays)
            monkeypatch.setattr(wired.PageAgentAnalyzer, "_classify_page",
                                lambda self, *a, **k: agent(*a, **k))
            doc, c = _paged_doc({0: 6, 1: 6, 2: 6, 3: 6})
            wired.PageAgentAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
            seen.append([
                (ch.visual_layout.page_or_screen_index,
                 (ch.metadata or {}).get("page_role"))
                for ch in c.children
            ])
        assert seen[0] == seen[1]


class TestCoverage:
    def test_sparse_pages_are_not_skipped(self, wired, monkeypatch):
        """MIN_BLOCKS was sized for a serial pipeline and skipped half the book."""
        agent = _FakeAgent()
        monkeypatch.setattr(wired.PageAgentAnalyzer, "_classify_page",
                            lambda self, *a, **k: agent(*a, **k))
        doc, _c = _paged_doc({0: 1, 1: 2, 2: 9})
        wired.PageAgentAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert sorted(agent.calls) == [0, 1, 2]


class TestFailureBudget:
    def test_one_bad_page_does_not_abort_the_rest(self, wired, monkeypatch):
        agent = _FakeAgent(fail_pages={1})
        monkeypatch.setattr(wired.PageAgentAnalyzer, "_classify_page",
                            lambda self, *a, **k: agent(*a, **k))
        doc, _c = _paged_doc({p: 6 for p in range(8)})
        wired.PageAgentAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert len(agent.calls) == 8, "a single failure stopped the run"

    def test_dead_agent_stops_the_run(self, wired, monkeypatch):
        agent = _FakeAgent(fail_pages=set(range(40)))
        monkeypatch.setattr(wired.PageAgentAnalyzer, "_classify_page",
                            lambda self, *a, **k: agent(*a, **k))
        doc, _c = _paged_doc({p: 6 for p in range(40)})
        wired.PageAgentAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert len(agent.calls) < 40, "every page was tried against a dead agent"


class TestSingleRoundTrip:
    def test_table_from_classify_avoids_second_call(self, wired, monkeypatch):
        recognize_calls = []
        monkeypatch.setattr(
            wired.PageAgentAnalyzer, "_classify_page",
            lambda self, *a, **k: ("table", {}, "\\begin{tabular}{l}x\\end{tabular}"),
        )
        monkeypatch.setattr(
            wired.PageAgentAnalyzer, "_recognize_table",
            lambda self, *a, **k: recognize_calls.append(1),
        )
        doc, _c = _paged_doc({0: 6})
        wired.PageAgentAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert recognize_calls == [], "table page still made a second request"

    def test_falls_back_to_crop_when_no_table_returned(self, wired, monkeypatch):
        recognize_calls = []

        def fake_recognize(self, *a, **k):
            recognize_calls.append(1)
            return "\\begin{tabular}{l}y\\end{tabular}"

        monkeypatch.setattr(wired.PageAgentAnalyzer, "_classify_page",
                            lambda self, *a, **k: ("table", {}, None))
        monkeypatch.setattr(wired.PageAgentAnalyzer, "_recognize_table", fake_recognize)
        doc, _c = _paged_doc({0: 6})
        wired.PageAgentAnalyzer().run(doc, ReadingGraph(), KnowledgeGraph())
        assert recognize_calls == [1]


class TestCleanTabular:
    def test_strips_markdown_fence(self):
        from src.analyzers.page_agent import _clean_tabular
        out = _clean_tabular("```latex\n\\begin{tabular}{l}x\\end{tabular}\n```")
        assert out.startswith("\\begin{tabular}")
        assert "```" not in out

    def test_rejects_non_table(self):
        from src.analyzers.page_agent import _clean_tabular
        assert _clean_tabular("just prose") is None
        assert _clean_tabular(None) is None
