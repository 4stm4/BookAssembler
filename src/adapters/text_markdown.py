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
import hashlib
import re
from typing import Any, BinaryIO, Dict, List, Optional

from src.adapters.base import (
    AdapterCapabilities,
    BaseSourceAdapter,
    SourceAdapterParseError,
)
from src.adapters._shared import ContainerStack, fallback_title, render_markdown
from src.krm.models import (
    ContainerUnit,
    InlineUnit,
    KnowledgeDocument,
    ParagraphBlock,
    ProvenanceInfo,
    StyledTextSpan,
    TextLineInline,
)


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
            source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )

        doc_title = fallback_title(source_uri)
        doc = KnowledgeDocument(
            title=doc_title,
            source_uri=source_uri,
            source_type="markdown",
            provenance_info=provenance,
        )

        stack = ContainerStack(doc, provenance)
        render_markdown(text_content, stack, doc, provenance)

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
            source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )

        doc_title = fallback_title(source_uri)
        doc = KnowledgeDocument(
            title=doc_title,
            source_uri=source_uri,
            source_type="text",
            provenance_info=provenance,
        )

        root_container = ContainerUnit(
            title=doc_title,
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
