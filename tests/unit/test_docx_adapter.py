"""DOCX source adapter (RFC 0008 §3.2, §5.1)."""

import io
import zipfile

import pytest

from src.adapters import create_default_registry
from src.adapters.base import SourceAdapterParseError
from src.adapters.docx_adapter import DocxSourceAdapter
from src.krm.models import (
    CaptionBlock,
    CodeBlock,
    ContainerUnit,
    ListBlock,
    ParagraphBlock,
    TableBlock,
)

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx(body_xml: str) -> io.BytesIO:
    document = f'<?xml version="1.0"?><w:document {_W}><w:body>{body_xml}</w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
    buffer.seek(0)
    return buffer


def _p(text: str, style: str = "", extra_ppr: str = "") -> str:
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    ppr = f"<w:pPr>{style_xml}{extra_ppr}</w:pPr>" if style_xml or extra_ppr else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _parse(body_xml: str):
    return DocxSourceAdapter().parse(_docx(body_xml), "file://sample.docx")


def _blocks(container: ContainerUnit):
    return [c for c in container.children if not isinstance(c, ContainerUnit)]


def test_styles_build_the_container_hierarchy() -> None:
    doc = _parse(
        _p("Assembly Manual", "Title")
        + _p("Chapter 1", "Heading1")
        + _p("Body text.")
        + _p("Section 1.1", "Heading2")
        + _p("Nested text.")
    )

    assert doc.title == "Assembly Manual"
    chapter = doc.root_containers[0]
    assert chapter.title == "Chapter 1"
    assert isinstance(_blocks(chapter)[0], ParagraphBlock)

    section = [c for c in chapter.children if isinstance(c, ContainerUnit)][0]
    assert section.title == "Section 1.1"
    assert section.level == 2


def test_outline_level_is_honoured_when_style_is_localized() -> None:
    """A localized style name still has w:outlineLvl, which states the level."""
    doc = _parse(
        _p("Kapitel 1", "berschrift1", extra_ppr='<w:outlineLvl w:val="0"/>')
        + _p("Text.")
    )

    heading = doc.root_containers[0]
    assert heading.title == "Kapitel 1"
    assert heading.level == 1


def test_caption_and_code_styles_map_to_their_blocks() -> None:
    doc = _parse(_p("Figure 1. Bus layout", "Caption") + _p("MOV R0, R1", "Code"))

    blocks = _blocks(doc.root_containers[0])
    assert isinstance(blocks[0], CaptionBlock)
    assert blocks[0].caption_text == "Figure 1. Bus layout"
    assert isinstance(blocks[1], CodeBlock)
    assert blocks[1].code_text == "MOV R0, R1"


def test_runs_keep_bold_and_italic_without_faking_geometry() -> None:
    body = (
        "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>"
        '<w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t> plain</w:t></w:r></w:p>'
    )
    doc = _parse(body)

    paragraph = _blocks(doc.root_containers[0])[0]
    spans = paragraph.inlines[0].spans
    assert spans[0].text == "bold"
    assert spans[0].metadata["is_bold"] is True
    assert spans[1].metadata == {}
    assert paragraph.visual_layout is None


def test_numbered_paragraphs_become_one_list() -> None:
    numbering = "<w:numPr><w:numId w:val=\"3\"/></w:numPr>"
    doc = _parse(
        _p("first", extra_ppr=numbering)
        + _p("second", extra_ppr=numbering)
        + _p("after the list")
    )

    blocks = _blocks(doc.root_containers[0])
    assert isinstance(blocks[0], ListBlock)
    assert len(blocks[0].items) == 2
    assert isinstance(blocks[1], ParagraphBlock)


def test_table_preserves_horizontal_and_vertical_merges() -> None:
    body = (
        "<w:tbl>"
        "<w:tr>"
        '<w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr><w:p><w:r><w:t>wide</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:tcPr><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>tall</w:t></w:r></w:p></w:tc>'
        "</w:tr>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>b</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc>"
        "</w:tr>"
        "</w:tbl>"
    )
    doc = _parse(body)

    table = _blocks(doc.root_containers[0])[0]
    assert isinstance(table, TableBlock)
    assert table.grid[0][0].col_span == 2
    assert table.grid[0][1].row_span == 2
    # the continuation cell is not repeated in the second row
    assert len(table.grid[1]) == 2


def test_registry_routes_docx_extension() -> None:
    adapter = create_default_registry().get_adapter_for_extension("docx")

    assert isinstance(adapter, DocxSourceAdapter)


def test_source_digest_is_recorded() -> None:
    doc = _parse(_p("text"))

    assert len(doc.provenance_info.source_sha256) == 64
    assert doc.source_type == "docx"


def test_corrupt_archive_raises_adapter_error() -> None:
    with pytest.raises(SourceAdapterParseError, match="readable archive"):
        DocxSourceAdapter().parse(io.BytesIO(b"not a zip"), "file://broken.docx")


def test_archive_without_document_part_raises_adapter_error() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/settings.xml", "<settings/>")
    buffer.seek(0)

    with pytest.raises(SourceAdapterParseError, match="no word/document.xml"):
        DocxSourceAdapter().parse(buffer, "file://empty.docx")


def test_malformed_xml_raises_adapter_error() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><unclosed>")
    buffer.seek(0)

    with pytest.raises(SourceAdapterParseError, match="Malformed"):
        DocxSourceAdapter().parse(buffer, "file://bad.docx")
