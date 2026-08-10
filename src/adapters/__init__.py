"""
Source Adapters package for Knowledge Assembly Engine (KAE).

Provides BaseSourceAdapter, AdapterCapabilities, AdapterRegistry, SourceAdapterParseError,
MarkdownSourceAdapter, TextSourceAdapter, and PdfSourceAdapter according to RFC 0008.
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


def create_default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(MarkdownSourceAdapter())
    registry.register(TextSourceAdapter())
    registry.register(PdfSourceAdapter())
    return registry


__all__ = [
    "AdapterCapabilities",
    "AdapterRegistry",
    "BaseSourceAdapter",
    "MarkdownSourceAdapter",
    "PdfSourceAdapter",
    "SourceAdapterParseError",
    "TextSourceAdapter",
    "create_default_registry",
]
