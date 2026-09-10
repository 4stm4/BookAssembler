"""
HTML / Wiki Source Adapter for Knowledge Assembly Engine (KAE), RFC 0008 §3.3.

Converts a web page into Unprocessed KRM: `<h1>`–`<h6>` build the container
hierarchy, `<pre><code>` becomes a CodeBlock, lists and tables keep the structure
the markup declares, and `<meta>` / OpenGraph tags land in document metadata.
Tags are read, never interpreted — no semantic analysis here (RFC 0008 §5.2).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (html.parser, hashlib)
- Exception wrapping: raises SourceAdapterParseError on unreadable input
"""

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
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
    FigureBlock,
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

_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_IGNORED = {"script", "style", "noscript", "template", "svg"}
_BLOCK_TEXT_TAGS = {"p", "blockquote", "figcaption", "dd", "dt"}
_LIST_STYLES = {"ul": "bullet", "ol": "ordered"}


def _attr(attrs: List[Tuple[str, Optional[str]]], name: str) -> str:
    for key, value in attrs:
        if key.lower() == name:
            return value or ""
    return ""


def _language_from_class(class_attr: str) -> Optional[str]:
    """`class="language-python"` / `class="lang-c"` — the page's own declaration."""
    for token in class_attr.split():
        for prefix in ("language-", "lang-", "highlight-"):
            if token.lower().startswith(prefix):
                return token[len(prefix):] or None
    return None


class _KrmHtmlParser(HTMLParser):
    """Streams HTML tags into KRM blocks under a ContainerStack."""

    def __init__(self, doc: KnowledgeDocument, provenance: ProvenanceInfo) -> None:
        super().__init__(convert_charrefs=True)
        self._doc = doc
        self._provenance = provenance
        self._stack = ContainerStack(doc, provenance)

        self._skip_depth = 0
        self._text: List[str] = []
        self._capture: Optional[str] = None

        self._heading_level: Optional[int] = None
        self._title_seen = False
        self._in_title_tag = False

        self._code_language: Optional[str] = None
        self._in_pre = False

        self._lists: List[ListBlock] = []
        self._list_items: List[ListItemBlock] = []

        self._table_rows: List[List[TableCell]] = []
        self._row: List[TableCell] = []
        self._cell_attrs: Optional[List[Tuple[str, Optional[str]]]] = None

    # -- text helpers ----------------------------------------------------

    def _flush_text(self) -> str:
        text = "".join(self._text)
        self._text = []
        return text if self._in_pre else " ".join(text.split())

    def _paragraph(self, text: str) -> ParagraphBlock:
        spans = [
            TextLineInline(
                spans=[StyledTextSpan(text=line, provenance_info=self._provenance)],
                provenance_info=self._provenance,
            )
            for line in text.splitlines()
            if line.strip()
        ]
        return ParagraphBlock(inlines=spans, provenance_info=self._provenance)

    def _emit(self, block: StructuralUnit) -> None:
        """Route a block into the open list item, table cell, or container."""
        if self._list_items:
            self._list_items[-1].content.append(block)
        else:
            self._stack.add(block)

    # -- HTMLParser hooks ------------------------------------------------

    def handle_starttag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        tag = tag.lower()

        if tag in _IGNORED:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag == "meta":
            self._meta(attrs)
            return
        if tag == "title":
            self._in_title_tag = True
            self._text = []
            return
        if tag == "img":
            self._emit(
                FigureBlock(
                    image_uri=_attr(attrs, "src") or None,
                    alt_text=_attr(attrs, "alt") or None,
                    provenance_info=self._provenance,
                )
            )
            return

        if tag in _HEADINGS:
            self._heading_level = _HEADINGS[tag]
            self._text = []
            return

        if tag == "pre":
            self._in_pre = True
            self._capture = "code"
            self._text = []
            return
        if tag == "code":
            language = _language_from_class(_attr(attrs, "class"))
            if language:
                self._code_language = language
            if not self._in_pre:
                return
            return

        if tag in _LIST_STYLES:
            self._lists.append(
                ListBlock(
                    list_style=_LIST_STYLES[tag], provenance_info=self._provenance
                )
            )
            return
        if tag == "li" and self._lists:
            self._list_items.append(ListItemBlock(provenance_info=self._provenance))
            self._text = []
            return

        if tag == "table":
            self._table_rows = []
            return
        if tag == "tr":
            self._row = []
            return
        if tag in ("td", "th"):
            self._cell_attrs = attrs
            self._text = []
            return

        if tag in _BLOCK_TEXT_TAGS:
            self._capture = tag
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in _IGNORED:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if tag == "title":
            text = self._flush_text().strip()
            self._in_title_tag = False
            if text and not self._title_seen:
                self._doc.title = text
                self._title_seen = True
            return

        if tag in _HEADINGS and self._heading_level is not None:
            text = self._flush_text().strip()
            level = self._heading_level
            self._heading_level = None
            if not text:
                return
            if level == 1 and not self._title_seen:
                self._doc.title = text
                self._title_seen = True
            self._stack.open(text, level)
            return

        if tag == "pre":
            code = self._flush_text()
            self._in_pre = False
            self._capture = None
            language = self._code_language
            self._code_language = None
            if code.strip():
                self._emit(
                    CodeBlock(
                        code_text=code.strip("\n"),
                        programming_language=language,
                        provenance_info=self._provenance,
                    )
                )
            return

        if tag == "li" and self._list_items:
            text = self._flush_text().strip()
            item = self._list_items.pop()
            if text:
                item.content.insert(0, self._paragraph(text))
            if item.content and self._lists:
                self._lists[-1].items.append(item)
            return

        if tag in _LIST_STYLES and self._lists:
            finished = self._lists.pop()
            if finished.items:
                self._emit(finished)
            return

        if tag in ("td", "th"):
            text = self._flush_text().strip()
            attrs = self._cell_attrs or []
            self._cell_attrs = None
            content: List[StructuralUnit] = [self._paragraph(text)] if text else []
            self._row.append(
                TableCell(
                    row_span=_span(attrs, "rowspan"),
                    col_span=_span(attrs, "colspan"),
                    content=content,
                    provenance_info=self._provenance,
                )
            )
            return

        if tag == "tr":
            if self._row:
                self._table_rows.append(self._row)
            self._row = []
            return

        if tag == "table":
            if self._table_rows:
                self._emit(
                    TableBlock(
                        grid=self._table_rows, provenance_info=self._provenance
                    )
                )
            self._table_rows = []
            return

        if tag == "figcaption":
            text = self._flush_text().strip()
            self._capture = None
            if text:
                self._emit(
                    CaptionBlock(
                        caption_text=text,
                        target_type="figure",
                        provenance_info=self._provenance,
                    )
                )
            return

        if tag in _BLOCK_TEXT_TAGS:
            text = self._flush_text().strip()
            self._capture = None
            if text:
                self._emit(self._paragraph(text))

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if (
            self._capture
            or self._heading_level is not None
            or self._in_title_tag
            or self._cell_attrs is not None
            or self._list_items
        ):
            self._text.append(data)

    def _meta(self, attrs: List[Tuple[str, Optional[str]]]) -> None:
        """Keep OpenGraph and named meta tags as document metadata (RFC 0008 §3.3)."""
        name = _attr(attrs, "name") or _attr(attrs, "property")
        content = _attr(attrs, "content")
        if not name or not content:
            return
        self._doc.metadata.setdefault("html_meta", {})[name] = content
        if name == "og:title" and not self._title_seen:
            self._doc.title = content
            self._title_seen = True

    def finish(self) -> None:
        if not self._doc.root_containers:
            self._stack.current()


def _span(attrs: List[Tuple[str, Optional[str]]], name: str) -> int:
    try:
        return max(1, int(_attr(attrs, name) or "1"))
    except ValueError:
        return 1


class HtmlSourceAdapter(BaseSourceAdapter):
    """Source Adapter for HTML pages and wiki exports (.html, .htm, .xhtml)."""

    def __init__(self, capabilities: Optional[AdapterCapabilities] = None) -> None:
        if capabilities is None:
            capabilities = AdapterCapabilities(
                adapter_name="HtmlSourceAdapter",
                supported_extensions=["html", "htm", "xhtml"],
                supported_mimeTypes=["text/html", "application/xhtml+xml"],
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
        """Parse an HTML binary stream into an Unprocessed KRM KnowledgeDocument."""
        if stream is None:
            raise SourceAdapterParseError("Input stream is None")

        try:
            raw_bytes = stream.read()
        except Exception as e:
            raise SourceAdapterParseError(f"Failed to read HTML stream: {e}") from e
        if not isinstance(raw_bytes, bytes):
            raise SourceAdapterParseError("Stream read did not return bytes")

        encoding = (options or {}).get("encoding", "utf-8")
        try:
            markup = raw_bytes.decode(encoding, errors="replace")
        except LookupError as e:
            raise SourceAdapterParseError(f"Unknown encoding {encoding!r}: {e}") from e

        provenance = ProvenanceInfo(
            adapter_name=self.capabilities.adapter_name,
            extraction_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )
        doc = KnowledgeDocument(
            title=fallback_title(source_uri),
            source_uri=source_uri,
            source_type="html",
            provenance_info=provenance,
        )

        parser = _KrmHtmlParser(doc, provenance)
        try:
            parser.feed(markup)
            parser.close()
        except Exception as e:
            raise SourceAdapterParseError(f"Failed to parse HTML: {e}") from e
        parser.finish()

        return doc
