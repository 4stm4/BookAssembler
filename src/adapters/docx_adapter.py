"""
DOCX Source Adapter for Knowledge Assembly Engine (KAE), RFC 0008 §3.2.

Reads the OpenXML part of a .docx and converts it to Unprocessed KRM: built-in
styles (Title, Heading 1..6, Caption, Code) select the block type, tables keep
their merges, and document order becomes reading order. Nothing is inferred —
a style the document declares is read, never guessed (RFC 0008 §5.2).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (zipfile, xml.etree, hashlib, re)
- Exception wrapping: raises SourceAdapterParseError on any malformed input
"""

from datetime import datetime, timezone
import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

from src.adapters._shared import ContainerStack, fallback_title
from src.adapters.base import (
    AdapterCapabilities,
    BaseSourceAdapter,
    SourceAdapterParseError,
)
from src.krm.models import (
    CaptionBlock,
    CodeBlock,
    InlineUnit,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    ParagraphBlock,
    ProvenanceInfo,
    StructuralUnit,
    StyledTextSpan,
    TableBlock,
    TableCell,
    TextLineInline,
)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DOCUMENT_PART = "word/document.xml"

_HEADING_STYLE_RE = re.compile(r"^heading\s*([1-6])$", re.IGNORECASE)
_CODE_STYLES = {"code", "sourcecode", "htmlpreformatted", "plaintext", "macrotext"}


def _style_id(paragraph: ET.Element) -> str:
    properties = paragraph.find(f"{_W}pPr")
    if properties is None:
        return ""
    style = properties.find(f"{_W}pStyle")
    return style.get(f"{_W}val", "") if style is not None else ""


def _outline_level(paragraph: ET.Element) -> Optional[int]:
    """Heading level declared through w:outlineLvl (0-based in OpenXML)."""
    properties = paragraph.find(f"{_W}pPr")
    if properties is None:
        return None
    outline = properties.find(f"{_W}outlineLvl")
    if outline is None:
        return None
    try:
        return int(outline.get(f"{_W}val", "")) + 1
    except ValueError:
        return None


def _heading_level(paragraph: ET.Element) -> Optional[int]:
    match = _HEADING_STYLE_RE.match(_style_id(paragraph).replace("-", " ").strip())
    if match:
        return int(match.group(1))

    level = _outline_level(paragraph)
    if level is not None and 1 <= level <= 6:
        return level
    return None


def _toggle_is_on(properties: Optional[ET.Element], tag: str) -> bool:
    """OpenXML toggle: present means on unless it carries val 0/false/off."""
    if properties is None:
        return False
    element = properties.find(f"{_W}{tag}")
    if element is None:
        return False
    return element.get(f"{_W}val", "true").lower() not in ("0", "false", "off")


def _runs(paragraph: ET.Element) -> List[Tuple[str, bool, bool]]:
    """(text, bold, italic) per run, with tabs and breaks kept as characters."""
    collected: List[Tuple[str, bool, bool]] = []
    for run in paragraph.iter(f"{_W}r"):
        pieces: List[str] = []
        for node in run:
            if node.tag == f"{_W}t":
                pieces.append(node.text or "")
            elif node.tag == f"{_W}tab":
                pieces.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                pieces.append("\n")
        text = "".join(pieces)
        if not text:
            continue
        properties = run.find(f"{_W}rPr")
        collected.append(
            (text, _toggle_is_on(properties, "b"), _toggle_is_on(properties, "i"))
        )
    return collected


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(text for text, _bold, _italic in _runs(paragraph))


def _inlines(paragraph: ET.Element, provenance: ProvenanceInfo) -> List[InlineUnit]:
    """One TextLineInline per source line; runs become spans keeping bold/italic.

    Character formatting goes to span metadata rather than VisualLayout.style:
    a .docx carries no coordinates, and a fabricated bounding box would be a lie
    the positional renderer later reads as real (RFC 0008 §3.2).
    """
    lines: List[List[StyledTextSpan]] = [[]]
    for text, bold, italic in _runs(paragraph):
        for index, part in enumerate(text.split("\n")):
            if index:
                lines.append([])
            if not part:
                continue
            span = StyledTextSpan(text=part, provenance_info=provenance)
            if bold or italic:
                span.metadata = {"is_bold": bold, "is_italic": italic}
            lines[-1].append(span)

    return [
        TextLineInline(spans=spans, provenance_info=provenance)
        for spans in lines
        if spans
    ]


def _list_marker(paragraph: ET.Element) -> Optional[str]:
    """Numbering id when the paragraph belongs to a declared w:numPr list."""
    properties = paragraph.find(f"{_W}pPr")
    if properties is None:
        return None
    numbering = properties.find(f"{_W}numPr")
    if numbering is None:
        return None
    num_id = numbering.find(f"{_W}numId")
    return num_id.get(f"{_W}val", "") if num_id is not None else ""


class DocxSourceAdapter(BaseSourceAdapter):
    """Source Adapter for Microsoft Word documents (.docx)."""

    def __init__(self, capabilities: Optional[AdapterCapabilities] = None) -> None:
        if capabilities is None:
            capabilities = AdapterCapabilities(
                adapter_name="DocxSourceAdapter",
                supported_extensions=["docx"],
                supported_mimeTypes=[
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ],
                provides_visual_layout=False,
                provides_reading_order=True,
            )
        super().__init__(capabilities)

    def parse(
        self,
        stream: BinaryIO,
        source_uri: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeDocument:
        """Parse a .docx binary stream into an Unprocessed KRM KnowledgeDocument."""
        if stream is None:
            raise SourceAdapterParseError("Input stream is None")

        try:
            raw_bytes = stream.read()
        except Exception as e:
            raise SourceAdapterParseError(f"Failed to read DOCX stream: {e}") from e
        if not isinstance(raw_bytes, bytes):
            raise SourceAdapterParseError("Stream read did not return bytes")

        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
                document_xml = archive.read(_DOCUMENT_PART)
        except KeyError as e:
            raise SourceAdapterParseError(
                f"DOCX archive has no {_DOCUMENT_PART} part"
            ) from e
        except (zipfile.BadZipFile, OSError) as e:
            raise SourceAdapterParseError(f"DOCX is not a readable archive: {e}") from e

        try:
            root = ET.fromstring(document_xml)
        except ET.ParseError as e:
            raise SourceAdapterParseError(f"Malformed {_DOCUMENT_PART}: {e}") from e

        body = root.find(f"{_W}body")
        if body is None:
            raise SourceAdapterParseError("DOCX document.xml has no w:body")

        provenance = ProvenanceInfo(
            adapter_name=self.capabilities.adapter_name,
            extraction_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )
        doc = KnowledgeDocument(
            title=fallback_title(source_uri),
            source_uri=source_uri,
            source_type="docx",
            provenance_info=provenance,
        )
        stack = ContainerStack(doc, provenance)

        pending_list: List[ListItemBlock] = []
        pending_num_id: Optional[str] = None

        def flush_list() -> None:
            nonlocal pending_list, pending_num_id
            if pending_list:
                stack.add(
                    ListBlock(items=pending_list, provenance_info=provenance)
                )
            pending_list = []
            pending_num_id = None

        for element in body:
            if element.tag == f"{_W}tbl":
                flush_list()
                stack.add(self._table(element, provenance))
                continue
            if element.tag != f"{_W}p":
                continue

            num_id = _list_marker(element)
            if num_id is not None and _paragraph_text(element).strip():
                if pending_num_id is not None and num_id != pending_num_id:
                    flush_list()
                pending_num_id = num_id
                item = ListItemBlock(provenance_info=provenance)
                item.content = [
                    ParagraphBlock(
                        inlines=_inlines(element, provenance),
                        provenance_info=provenance,
                    )
                ]
                pending_list.append(item)
                continue

            flush_list()
            self._add_paragraph(element, stack, doc, provenance)

        flush_list()

        if not doc.root_containers:
            stack.current()
        return doc

    def _add_paragraph(
        self,
        paragraph: ET.Element,
        stack: ContainerStack,
        doc: KnowledgeDocument,
        provenance: ProvenanceInfo,
    ) -> None:
        text = _paragraph_text(paragraph).strip()
        style = _style_id(paragraph).lower().replace(" ", "")

        # Word's Title style names the document, it does not open a section:
        # opening one would be evicted by the first Heading 1 anyway.
        if style == "title" and text:
            doc.title = text
            return

        level = _heading_level(paragraph)
        if level is not None and text:
            stack.open(text, level)
            return

        if not text:
            return

        if style == "caption":
            stack.add(CaptionBlock(caption_text=text, provenance_info=provenance))
            return

        if style in _CODE_STYLES:
            stack.add(CodeBlock(code_text=text, provenance_info=provenance))
            return

        stack.add(
            ParagraphBlock(
                inlines=_inlines(paragraph, provenance), provenance_info=provenance
            )
        )

    def _table(self, table: ET.Element, provenance: ProvenanceInfo) -> TableBlock:
        """Build a TableBlock preserving gridSpan/vMerge as col_span/row_span."""
        grid: List[List[TableCell]] = []
        open_merges: Dict[int, TableCell] = {}

        for row in table.findall(f"{_W}tr"):
            row_cells: List[TableCell] = []
            column = 0

            for cell_element in row.findall(f"{_W}tc"):
                properties = cell_element.find(f"{_W}tcPr")
                col_span = _grid_span(properties)
                merge = (
                    properties.find(f"{_W}vMerge") if properties is not None else None
                )

                if merge is not None and merge.get(f"{_W}val", "continue") != "restart":
                    origin = open_merges.get(column)
                    if origin is not None:
                        origin.row_span += 1
                    column += col_span
                    continue

                content: List[StructuralUnit] = [
                    ParagraphBlock(
                        inlines=_inlines(paragraph, provenance),
                        provenance_info=provenance,
                    )
                    for paragraph in cell_element.findall(f"{_W}p")
                    if _paragraph_text(paragraph).strip()
                ]
                cell = TableCell(
                    col_span=col_span, content=content, provenance_info=provenance
                )

                if merge is not None:
                    open_merges[column] = cell
                else:
                    open_merges.pop(column, None)

                row_cells.append(cell)
                column += col_span

            grid.append(row_cells)

        return TableBlock(grid=grid, provenance_info=provenance)


def _grid_span(properties: Optional[ET.Element]) -> int:
    if properties is None:
        return 1
    span = properties.find(f"{_W}gridSpan")
    if span is None:
        return 1
    try:
        return max(1, int(span.get(f"{_W}val", "1")))
    except ValueError:
        return 1
