"""
Source Adapters package for Knowledge Assembly Engine (KAE).

Provides BaseSourceAdapter, AdapterCapabilities, AdapterRegistry, SourceAdapterParseError,
MarkdownSourceAdapter, and TextSourceAdapter according to RFC 0008 (docs/architecture/0008-adapters.md).
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

__all__ = [
    "AdapterCapabilities",
    "AdapterRegistry",
    "BaseSourceAdapter",
    "MarkdownSourceAdapter",
    "SourceAdapterParseError",
    "TextSourceAdapter",
]
