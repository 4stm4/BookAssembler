"""
Markdown and Text Source Adapters for Knowledge Assembly Engine (KAE).

Implements MarkdownSourceAdapter and TextSourceAdapter according to
RFC 0008 (docs/architecture/0008-adapters.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, datetime, re, uuid)
- Converts raw Markdown/Text streams into Unprocessed KRM KnowledgeDocument
- Source isolation: returns canonical KRM structures only
- Exception wrapping: raises SourceAdapterParseError on parsing or decoding failures
"""

from datetime import datetime, timezone
import re
from typing import Any, BinaryIO, Dict, List, Optional

from src.adapters.base import (
    AdapterCapabilities,
    BaseSourceAdapter,
    SourceAdapterParseError,
)
from src.krm.models import (
    CodeBlock,
    ContainerUnit,
    InlineUnit,
    KnowledgeDocument,
    ParagraphBlock,
    ProvenanceInfo,
    StyledTextSpan,
    TextLineInline,
)


def _get_fallback_title(source_uri: str) -> str:
    """
    Derives a fallback title from the source URI string.
    """
    if not source_uri:
        return "Untitled Document"
    base_name = source_uri.rstrip("/").split("/")[-1].split("?")[0]
    if "." in base_name:
        derived = base_name.rsplit(".", 1)[0]
        return derived if derived else "Untitled Document"
    return base_name if base_name else "Untitled Document"


class MarkdownSourceAdapter(BaseSourceAdapter):
    """
    Source Adapter for Markdown files (.md, .markdown).

    Parses Markdown structure into a hierarchy of ContainerUnit nodes based on
    header levels (# to ######), ParagraphBlock nodes, and CodeBlock nodes.
    """

    def __init__(self, capabilities: Optional[AdapterCapabilities] = None) -> None:
        if capabilities is None:
            capabilities = AdapterCapabilities(
                adapter_name="MarkdownSourceAdapter",
                supported_extensions=["md", "markdown"],
                supported_mimeTypes=["text/markdown", "text/x-markdown"],
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
        """
        Parses Markdown binary stream into an Unprocessed KRM KnowledgeDocument.
        """
        try:
            if stream is None:
                raise SourceAdapterParseError("Input stream is None")
            raw_bytes = stream.read()
            if not isinstance(raw_bytes, bytes):
                raise SourceAdapterParseError("Stream read did not return bytes")
            text_content = raw_bytes.decode("utf-8")
        except SourceAdapterParseError:
            raise
        except Exception as e:
            raise SourceAdapterParseError(f"Failed to read or decode Markdown stream: {e}") from e

        timestamp = datetime.now(timezone.utc).isoformat()
        provenance = ProvenanceInfo(
            adapter_name=self.capabilities.adapter_name,
            extraction_timestamp_utc=timestamp,
        )

        fallback_title = _get_fallback_title(source_uri)
        doc = KnowledgeDocument(
            title=fallback_title,
            source_uri=source_uri,
            source_type="markdown",
            provenance_info=provenance,
        )

        doc_title_updated = False
        container_stack: List[ContainerUnit] = []

        def get_current_container() -> ContainerUnit:
            if not container_stack:
                root_c = ContainerUnit(
                    title=doc.title or "Main Content",
                    level=1,
                    provenance_info=provenance,
                )
                doc.root_containers.append(root_c)
                container_stack.append(root_c)
            return container_stack[-1]

        in_code_block = False
        code_language: Optional[str] = None
        code_lines: List[str] = []
        paragraph_lines: List[str] = []

        def flush_paragraph() -> None:
            nonlocal paragraph_lines
            if not paragraph_lines:
                return
            p_text = "\n".join(paragraph_lines).strip()
            paragraph_lines = []
            if not p_text:
                return

            inlines: List[InlineUnit] = []
            for line_str in p_text.splitlines():
                if line_str.strip():
                    span = StyledTextSpan(text=line_str.strip())
                    inlines.append(TextLineInline(spans=[span]))

            if not inlines:
                return

            curr_container = get_current_container()
            para = ParagraphBlock(
                inlines=inlines,
                parent_container_id=curr_container.id,
                provenance_info=provenance,
            )
            curr_container.children.append(para)

        def flush_code_block() -> None:
            nonlocal code_lines, code_language
            code_text = "\n".join(code_lines)
            curr_container = get_current_container()
            cblock = CodeBlock(
                code_text=code_text,
                programming_language=code_language if code_language else None,
                parent_container_id=curr_container.id,
                provenance_info=provenance,
            )
            curr_container.children.append(cblock)
            code_lines = []
            code_language = None

        lines = text_content.splitlines()
        for line in lines:
            stripped_line = line.strip()

            if stripped_line.startswith("```"):
                if in_code_block:
                    flush_code_block()
                    in_code_block = False
                else:
                    flush_paragraph()
                    in_code_block = True
                    lang = stripped_line[3:].strip()
                    code_language = lang if lang else None
                    code_lines = []
                continue

            if in_code_block:
                code_lines.append(line)
                continue

            header_match = re.match(r"^(#{1,6})\s+(.+)$", stripped_line)
            if header_match:
                flush_paragraph()
                level = len(header_match.group(1))
                heading_title = header_match.group(2).strip()

                if level == 1 and not doc_title_updated:
                    doc.title = heading_title
                    doc_title_updated = True

                new_container = ContainerUnit(
                    title=heading_title,
                    level=level,
                    provenance_info=provenance,
                )

                while container_stack and container_stack[-1].level >= level:
                    container_stack.pop()

                if not container_stack:
                    doc.root_containers.append(new_container)
                else:
                    new_container.parent_container_id = container_stack[-1].id
                    container_stack[-1].children.append(new_container)

                container_stack.append(new_container)
                continue

            if not stripped_line:
                flush_paragraph()
            else:
                paragraph_lines.append(line)

        if in_code_block:
            flush_code_block()
        else:
            flush_paragraph()

        if not doc.root_containers:
            doc.root_containers.append(
                ContainerUnit(
                    title=doc.title or "Document Content",
                    level=1,
                    provenance_info=provenance,
                )
            )

        return doc


class TextSourceAdapter(BaseSourceAdapter):
    """
    Source Adapter for plain text files (.txt).

    Parses plain text streams into ParagraphBlock nodes inside a root ContainerUnit.
    """

    def __init__(self, capabilities: Optional[AdapterCapabilities] = None) -> None:
        if capabilities is None:
            capabilities = AdapterCapabilities(
                adapter_name="TextSourceAdapter",
                supported_extensions=["txt"],
                supported_mimeTypes=["text/plain"],
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
        """
        Parses plain text binary stream into an Unprocessed KRM KnowledgeDocument.
        """
        try:
            if stream is None:
                raise SourceAdapterParseError("Input stream is None")
            raw_bytes = stream.read()
            if not isinstance(raw_bytes, bytes):
                raise SourceAdapterParseError("Stream read did not return bytes")
            text_content = raw_bytes.decode("utf-8")
        except SourceAdapterParseError:
            raise
        except Exception as e:
            raise SourceAdapterParseError(f"Failed to read or decode Text stream: {e}") from e

        timestamp = datetime.now(timezone.utc).isoformat()
        provenance = ProvenanceInfo(
            adapter_name=self.capabilities.adapter_name,
            extraction_timestamp_utc=timestamp,
        )

        fallback_title = _get_fallback_title(source_uri)
        doc = KnowledgeDocument(
            title=fallback_title,
            source_uri=source_uri,
            source_type="text",
            provenance_info=provenance,
        )

        root_container = ContainerUnit(
            title=fallback_title,
            level=1,
            provenance_info=provenance,
        )
        doc.root_containers.append(root_container)

        raw_paragraphs = [p.strip() for p in text_content.split("\n\n") if p.strip()]
        for p_text in raw_paragraphs:
            inlines: List[InlineUnit] = []
            for line_str in p_text.splitlines():
                if line_str.strip():
                    span = StyledTextSpan(text=line_str.strip())
                    inlines.append(TextLineInline(spans=[span]))

            if inlines:
                para = ParagraphBlock(
                    inlines=inlines,
                    parent_container_id=root_container.id,
                    provenance_info=provenance,
                )
                root_container.children.append(para)

        return doc
