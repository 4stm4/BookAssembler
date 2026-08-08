"""
Source Adapters Base Architecture and Registry for Knowledge Assembly Engine (KAE).

Defines SourceAdapterParseError, AdapterCapabilities, BaseSourceAdapter abstract class,
and AdapterRegistry according to RFC 0008 (docs/architecture/0008-adapters.md).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (dataclasses, typing, abc)
- Stream safety (BinaryIO interface)
- Exception wrapping (SourceAdapterParseError)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, BinaryIO, Dict, List, Optional

from src.krm.models import KnowledgeDocument


class SourceAdapterParseError(Exception):
    """
    Unified exception raised when a source adapter fails to parse an input stream.
    """
    pass


@dataclass(frozen=True)
class AdapterCapabilities:
    """
    Metadata describing capabilities and supported formats of a source adapter.
    """
    adapter_name: str
    supported_extensions: List[str]
    supported_mimeTypes: List[str]
    provides_visual_layout: bool
    provides_reading_order: bool


class BaseSourceAdapter(ABC):
    """
    Abstract base class for all source adapters in KAE.
    Converts raw binary streams into Unprocessed KRM KnowledgeDocument instances.
    """

    def __init__(self, capabilities: AdapterCapabilities) -> None:
        self._capabilities = capabilities

    @property
    def capabilities(self) -> AdapterCapabilities:
        """
        Returns the capabilities descriptor for this adapter.
        """
        return self._capabilities

    @abstractmethod
    def parse(
        self,
        stream: BinaryIO,
        source_uri: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeDocument:
        """
        Parses a binary input stream into an Unprocessed KRM KnowledgeDocument.

        Guarantees:
        1. Hierarchical structure creation (KnowledgeDocument -> ContainerUnit -> StructuralUnit).
        2. Assigns a unique UUIDv4 to every created node.
        3. Populates ProvenanceInfo with adapter metadata.
        4. Wraps any input stream parsing errors in SourceAdapterParseError.
        """
        pass


class AdapterRegistry:
    """
    Registry for managing and looking up available SourceAdapters by file extension or MIME type.
    """

    def __init__(self) -> None:
        self._adapters: List[BaseSourceAdapter] = []

    def register(self, adapter: BaseSourceAdapter) -> None:
        """
        Registers a source adapter instance.
        """
        if adapter not in self._adapters:
            self._adapters.append(adapter)

    def get_adapter_for_extension(self, ext: str) -> Optional[BaseSourceAdapter]:
        """
        Finds a registered adapter supporting the specified file extension (e.g., 'md', '.pdf').
        """
        clean_ext = ext.strip().lstrip(".").lower()
        if not clean_ext:
            return None

        for adapter in self._adapters:
            supported = [e.strip().lstrip(".").lower() for e in adapter.capabilities.supported_extensions]
            if clean_ext in supported:
                return adapter
        return None

    def get_adapter_for_mime(self, mime: str) -> Optional[BaseSourceAdapter]:
        """
        Finds a registered adapter supporting the specified MIME type (e.g., 'text/markdown').
        """
        clean_mime = mime.split(";")[0].strip().lower()
        if not clean_mime:
            return None

        for adapter in self._adapters:
            supported = [m.split(";")[0].strip().lower() for m in adapter.capabilities.supported_mimeTypes]
            if clean_mime in supported:
                return adapter
        return None
