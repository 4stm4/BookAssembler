"""HTML source adapter (RFC 0008 §3.3, §5.1)."""

import io

import pytest

from src.adapters import create_default_registry
from src.adapters.base import SourceAdapterParseError
from src.adapters.html_adapter import HtmlSourceAdapter
from src.krm.models import (
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    FigureBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
)


def _parse(markup: str):
    return HtmlSourceAdapter().parse(
        io.BytesIO(markup.encode("utf-8")), "file://page.html"
    )


def _blocks(container: ContainerUnit):
    return [c for c in container.children if not isinstance(c, ContainerUnit)]


def _text(paragraph: ParagraphBlock) -> str:
    return " ".join(
        span.text for inline in paragraph.inlines for span in inline.spans
    )


def test_headings_build_the_container_hierarchy() -> None:
    doc = _parse(
        "<h1>PDP-11 Handbook</h1><p>Intro.</p>"
        "<h2>Registers</h2><p>R0 through R7.</p>"
        "<h3>Stack pointer</h3><p>R6.</p>"
    )

    handbook = doc.root_containers[0]
    assert doc.title == "PDP-11 Handbook"
    assert handbook.title == "PDP-11 Handbook"

    registers = [c for c in handbook.children if isinstance(c, ContainerUnit)][0]
    assert registers.title == "Registers"
    assert registers.level == 2
    assert [c.title for c in registers.children if isinstance(c, ContainerUnit)] == [
        "Stack pointer"
    ]


def test_title_tag_and_opengraph_become_metadata() -> None:
    doc = _parse(
        "<html><head><title>Doc title</title>"
        '<meta name="author" content="DEC"/>'
        '<meta property="og:description" content="A handbook"/>'
        "</head><body><p>text</p></body></html>"
    )

    assert doc.title == "Doc title"
    assert doc.metadata["html_meta"]["author"] == "DEC"
    assert doc.metadata["html_meta"]["og:description"] == "A handbook"


def test_pre_code_becomes_a_codeblock_with_declared_language() -> None:
    doc = _parse('<pre><code class="language-asm">MOV R0, R1\n  HALT</code></pre>')

    block = _blocks(doc.root_containers[0])[0]
    assert isinstance(block, CodeBlock)
    assert block.programming_language == "asm"
    assert block.code_text == "MOV R0, R1\n  HALT"


def test_code_whitespace_is_preserved_but_prose_is_collapsed() -> None:
    doc = _parse("<pre><code>a    b</code></pre><p>a    b</p>")

    blocks = _blocks(doc.root_containers[0])
    assert blocks[0].code_text == "a    b"
    assert _text(blocks[1]) == "a b"


def test_lists_keep_declared_structure() -> None:
    doc = _parse("<ol><li>first</li><li>second</li></ol>")

    block = _blocks(doc.root_containers[0])[0]
    assert isinstance(block, ListBlock)
    assert block.list_style == "ordered"
    assert [_text(item.content[0]) for item in block.items] == ["first", "second"]


def test_table_keeps_rowspan_and_colspan() -> None:
    doc = _parse(
        "<table><tr><td colspan='2'>wide</td><td rowspan='2'>tall</td></tr>"
        "<tr><td>a</td><td>b</td></tr></table>"
    )

    table = _blocks(doc.root_containers[0])[0]
    assert isinstance(table, TableBlock)
    assert table.grid[0][0].col_span == 2
    assert table.grid[0][1].row_span == 2
    assert len(table.grid[1]) == 2


def test_figure_and_caption() -> None:
    doc = _parse(
        '<figure><img src="bus.png" alt="Bus layout"/>'
        "<figcaption>Figure 1. Bus</figcaption></figure>"
    )

    blocks = _blocks(doc.root_containers[0])
    assert isinstance(blocks[0], FigureBlock)
    assert blocks[0].image_uri == "bus.png"
    assert blocks[0].alt_text == "Bus layout"
    assert isinstance(blocks[1], CaptionBlock)
    assert blocks[1].caption_text == "Figure 1. Bus"


def test_script_and_style_content_is_dropped() -> None:
    doc = _parse(
        "<style>p { color: red }</style>"
        "<script>var x = 'not content';</script>"
        "<p>real text</p>"
    )

    blocks = _blocks(doc.root_containers[0])
    assert len(blocks) == 1
    assert _text(blocks[0]) == "real text"


def test_entities_are_decoded() -> None:
    doc = _parse("<p>A &amp; B &lt;tag&gt;</p>")

    assert _text(_blocks(doc.root_containers[0])[0]) == "A & B <tag>"


def test_document_without_headings_still_has_one_root() -> None:
    doc = _parse("<p>orphan paragraph</p>")

    assert len(doc.root_containers) == 1
    assert len(_blocks(doc.root_containers[0])) == 1


def test_registry_routes_html_extensions() -> None:
    registry = create_default_registry()

    assert isinstance(registry.get_adapter_for_extension("html"), HtmlSourceAdapter)
    assert isinstance(registry.get_adapter_for_extension("htm"), HtmlSourceAdapter)


def test_source_digest_is_recorded() -> None:
    doc = _parse("<p>text</p>")

    assert len(doc.provenance_info.source_sha256) == 64
    assert doc.source_type == "html"


def test_none_stream_raises_adapter_error() -> None:
    with pytest.raises(SourceAdapterParseError):
        HtmlSourceAdapter().parse(None, "file://page.html")  # type: ignore[arg-type]


def test_undecodable_bytes_do_not_crash() -> None:
    doc = HtmlSourceAdapter().parse(
        io.BytesIO(b"<p>\xff\xfe broken</p>"), "file://page.html"
    )

    assert len(doc.root_containers) == 1
