"""Tests for src/assembler/page_assembler — page-aware document reconstruction."""
import pytest
from src.assembler.page_assembler import (
    PageSlot,
    assemble_pages,
    group_by_page,
    _render_positional,
    _render_reflow,
)
from src.krm.models import (
    BlankPageBlock,
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    FormulaBlock,
    KnowledgeDocument,
    NormalizedRect,
    ParagraphBlock,
    StyledTextSpan,
    TextLineInline,
    TitlePageBlock,
    TocEntryBlock,
    VisualLayout,
)


def _para(text: str, page: int = 0, x0: float = 0.1, y0: float = 0.1,
          x1: float = 0.9, y1: float = 0.15) -> ParagraphBlock:
    p = ParagraphBlock(
        inlines=[TextLineInline(spans=[StyledTextSpan(text=text)])],
        visual_layout=VisualLayout(
            bounding_box=NormalizedRect(x0, y0, x1, y1),
            page_or_screen_index=page,
        ),
    )
    return p


def _doc(*containers: ContainerUnit) -> KnowledgeDocument:
    return KnowledgeDocument(
        title="Test",
        root_containers=list(containers),
    )


class TestGroupByPage:
    def test_groups_blocks_by_page(self):
        c = ContainerUnit(title="ch1", children=[
            _para("A", page=0, y0=0.5, y1=0.6),
            _para("B", page=0, y0=0.1, y1=0.2),
            _para("C", page=1),
        ])
        pages = group_by_page(_doc(c))
        assert 0 in pages
        assert 1 in pages
        assert len(pages[0].blocks) == 2
        assert len(pages[1].blocks) == 1

    def test_sorted_by_y0(self):
        c = ContainerUnit(title="ch1", children=[
            _para("Bottom", page=0, y0=0.8, y1=0.9),
            _para("Top", page=0, y0=0.1, y1=0.2),
        ])
        pages = group_by_page(_doc(c))
        texts = [b.inlines[0].spans[0].text for b in pages[0].blocks]
        assert texts == ["Top", "Bottom"]

    def test_tombstoned_excluded(self):
        p = _para("Gone", page=0)
        p.is_tombstoned = True
        c = ContainerUnit(title="ch1", children=[p, _para("Here", page=0)])
        pages = group_by_page(_doc(c))
        assert len(pages[0].blocks) == 1

    def test_title_page_role(self):
        tp = TitlePageBlock(
            book_title="My Book", page_role="cover",
            inlines=[TextLineInline(spans=[StyledTextSpan(text="My Book")])],
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.2, 0.3, 0.8, 0.5),
                page_or_screen_index=0,
            ),
        )
        c = ContainerUnit(title="front", children=[tp])
        pages = group_by_page(_doc(c))
        assert pages[0].role == "cover"

    def test_toc_page_role(self):
        toc = TocEntryBlock(
            entry_text="Chapter 1", target_page=5,
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.1, 0.1, 0.9, 0.15),
                page_or_screen_index=2,
            ),
        )
        c = ContainerUnit(title="toc", children=[toc])
        pages = group_by_page(_doc(c))
        assert pages[2].role == "toc"

    def test_blank_page_role(self):
        bp = BlankPageBlock(
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
                page_or_screen_index=3,
            ),
        )
        c = ContainerUnit(title="blank", children=[bp])
        pages = group_by_page(_doc(c))
        assert pages[3].role == "blank"


class TestRenderPositional:
    def test_tikz_output(self):
        tp = TitlePageBlock(
            book_title="Hello", page_role="title",
            inlines=[TextLineInline(spans=[StyledTextSpan(text="Hello World")])],
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.2, 0.3, 0.8, 0.5),
                page_or_screen_index=0,
            ),
        )
        slot = PageSlot(page_index=0, role="title", blocks=[tp])
        out = _render_positional(slot, "")
        assert "tikzpicture" in out
        assert "Hello World" in out
        assert "clearpage" in out

    def test_toc_positional(self):
        toc = TocEntryBlock(
            entry_text="Introduction", target_page=4,
            chapter_number="1",
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.1, 0.2, 0.9, 0.25),
                page_or_screen_index=1,
            ),
        )
        slot = PageSlot(page_index=1, role="toc", blocks=[toc])
        out = _render_positional(slot, "")
        assert "Introduction" in out
        assert "tikzpicture" in out


class TestRenderReflow:
    def test_paragraph_reflow(self):
        slot = PageSlot(page_index=0, role="text", blocks=[
            _para("First paragraph"),
            _para("Second paragraph", y0=0.3, y1=0.4),
        ])
        out = _render_reflow(slot, "")
        assert "First paragraph" in out
        assert "Second paragraph" in out

    def test_code_block(self):
        cb = CodeBlock(
            code_text="print('hello')",
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.1, 0.1, 0.9, 0.3),
                page_or_screen_index=0,
            ),
        )
        slot = PageSlot(page_index=0, role="text", blocks=[cb])
        out = _render_reflow(slot, "")
        assert "verbatim" in out
        assert "print('hello')" in out

    def test_formula_block(self):
        fb = FormulaBlock(
            latex_expression="E = mc^2",
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.1, 0.1, 0.9, 0.2),
                page_or_screen_index=0,
            ),
        )
        slot = PageSlot(page_index=0, role="text", blocks=[fb])
        out = _render_reflow(slot, "")
        assert "E = mc^2" in out


class TestAssemblePages:
    def test_mixed_pages(self):
        tp = TitlePageBlock(
            book_title="Book", page_role="title",
            inlines=[TextLineInline(spans=[StyledTextSpan(text="My Book")])],
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.2, 0.3, 0.8, 0.5),
                page_or_screen_index=0,
            ),
        )
        text = _para("Content here", page=1)
        blank = BlankPageBlock(
            visual_layout=VisualLayout(
                bounding_box=NormalizedRect(0.0, 0.0, 1.0, 1.0),
                page_or_screen_index=2,
            ),
        )
        c = ContainerUnit(title="all", children=[tp, text, blank])
        doc = _doc(c)
        out = assemble_pages(doc)
        assert "tikzpicture" in out
        assert "My Book" in out
        assert "Content here" in out
        assert "clearpage" in out

    def test_page_order_preserved(self):
        p1 = _para("Page one", page=0)
        p2 = _para("Page two", page=1)
        p3 = _para("Page three", page=2)
        c = ContainerUnit(title="ch", children=[p3, p1, p2])
        doc = _doc(c)
        out = assemble_pages(doc)
        idx1 = out.index("Page one")
        idx2 = out.index("Page two")
        idx3 = out.index("Page three")
        assert idx1 < idx2 < idx3

    def test_translation_used(self):
        p = _para("English text", page=0)
        p.metadata = {"translations": {"ru": {"target_text": "Русский текст"}}}
        c = ContainerUnit(title="ch", children=[p])
        doc = _doc(c)
        out = assemble_pages(doc, target_lang="ru")
        assert "Русский текст" in out
        assert "English text" not in out
