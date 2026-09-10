"""
Source Adapters package for Knowledge Assembly Engine (KAE).

Provides BaseSourceAdapter, AdapterCapabilities, AdapterRegistry, SourceAdapterParseError,
MarkdownSourceAdapter, TextSourceAdapter, PdfSourceAdapter, DocxSourceAdapter, HtmlSourceAdapter and
NotebookSourceAdapter according to RFC 0008.
"""

from src.adapters.base import (
    AdapterCapabilities,
    AdapterRegistry,
    BaseSourceAdapter,
    SourceAdapterParseError,
)
from src.adapters.text_markdown import (
    MarkdownSourceAdapter,
    TextSourceAdapter,
)
from src.adapters.pdf_adapter import PdfSourceAdapter
from src.adapters.docx_adapter import DocxSourceAdapter
from src.adapters.html_adapter import HtmlSourceAdapter
from src.adapters.notebook_adapter import NotebookSourceAdapter


def create_default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(MarkdownSourceAdapter())
    registry.register(TextSourceAdapter())
    registry.register(PdfSourceAdapter())
    registry.register(DocxSourceAdapter())
    registry.register(HtmlSourceAdapter())
    registry.register(NotebookSourceAdapter())
    return registry


__all__ = [
    "AdapterCapabilities",
    "AdapterRegistry",
    "BaseSourceAdapter",
    "DocxSourceAdapter",
    "HtmlSourceAdapter",
    "MarkdownSourceAdapter",
    "NotebookSourceAdapter",
    "PdfSourceAdapter",
    "SourceAdapterParseError",
    "TextSourceAdapter",
    "create_default_registry",
]
