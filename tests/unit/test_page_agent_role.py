"""PageAgent persists the vision-derived page role so the assembler can use it."""
import pytest

from src.analyzers.page_agent import PageAgentAnalyzer
from src.assembler.page_assembler import group_by_page
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
