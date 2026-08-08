"""
Unit tests for Source Adapters and AdapterRegistry (RFC 0008).

Tests verify:
1. AdapterRegistry registration and lookup by extension and MIME type.
2. MarkdownSourceAdapter parsing hierarchy, headers, paragraphs, and code blocks.
3. TextSourceAdapter parsing plain text streams into ParagraphBlocks.
4. Exception wrapping in SourceAdapterParseError on corrupted streams.
"""

import contextlib
import io
import re
from typing import Any

try:
    import pytest
except ImportError:
    @contextlib.contextmanager
    def _pytest_raises_fallback(expected_exception: type[BaseException], match: str | None = None) -> Any:
        try:
            yield
        except expected_exception as e:
            if match and not re.search(match, str(e)):
                raise AssertionError(f"Pattern '{match}' not found in exception message: '{e}'")
        else:
            raise AssertionError(f"Expected exception {expected_exception} was not raised")

    class _PytestShim:
        raises = staticmethod(_pytest_raises_fallback)

    pytest = _PytestShim()  # type: ignore[assignment]


from src.adapters import (
    AdapterRegistry,
    MarkdownSourceAdapter,
    SourceAdapterParseError,
    TextSourceAdapter,
)
from src.krm.models import (
    CodeBlock,
    ContainerUnit,
    ParagraphBlock,
    TextLineInline,
)


def test_adapter_registry() -> None:
    """Verify registration and lookup of adapters in AdapterRegistry."""
    registry = AdapterRegistry()
    md_adapter = MarkdownSourceAdapter()
    txt_adapter = TextSourceAdapter()

    registry.register(md_adapter)
    registry.register(txt_adapter)

    # Extension lookup
    assert registry.get_adapter_for_extension("md") is md_adapter
    assert registry.get_adapter_for_extension(".markdown") is md_adapter
    assert registry.get_adapter_for_extension("MARKDOWN") is md_adapter
    assert registry.get_adapter_for_extension("txt") is txt_adapter
    assert registry.get_adapter_for_extension(".TXT") is txt_adapter
    assert registry.get_adapter_for_extension("pdf") is None

    # MIME lookup
    assert registry.get_adapter_for_mime("text/markdown") is md_adapter
    assert registry.get_adapter_for_mime("text/x-markdown; charset=utf-8") is md_adapter
    assert registry.get_adapter_for_mime("text/plain") is txt_adapter
    assert registry.get_adapter_for_mime("application/pdf") is None


def test_markdown_source_adapter_parsing() -> None:
    """Verify parsing of Markdown headers, hierarchy, paragraphs, and code blocks."""
    md_content = """# Architecture Manual
Introductory paragraph about Knowledge Assembly Engine.

## Module 1: Parser
Parser paragraph text.

```python
def parse_stream(stream):
    return stream.read()
```

### Details
Detailed explanation here.

## Module 2: Adapters
Adapters paragraph text.
"""

    stream = io.BytesIO(md_content.encode("utf-8"))
    adapter = MarkdownSourceAdapter()
    doc = adapter.parse(stream, source_uri="/docs/manual.md")

    assert doc.title == "Architecture Manual"
    assert doc.source_type == "markdown"
    assert doc.provenance_info is not None
    assert doc.provenance_info.adapter_name == "MarkdownSourceAdapter"

    assert len(doc.root_containers) == 1
    root = doc.root_containers[0]
    assert root.title == "Architecture Manual"
    assert root.level == 1

    # Check children of root container: Paragraph, Module 1 Container, Module 2 Container
    assert len(root.children) == 3

    # Child 0: ParagraphBlock
    assert isinstance(root.children[0], ParagraphBlock)

    # Child 1: ContainerUnit "Module 1: Parser"
    mod1 = root.children[1]
    assert isinstance(mod1, ContainerUnit)
    assert mod1.title == "Module 1: Parser"
    assert mod1.level == 2

    # Children of Module 1: Paragraph, CodeBlock, Details Container
    assert len(mod1.children) == 3
    assert isinstance(mod1.children[0], ParagraphBlock)

    code_node = mod1.children[1]
    assert isinstance(code_node, CodeBlock)
    assert code_node.programming_language == "python"
    assert "def parse_stream(stream):" in code_node.code_text

    details_node = mod1.children[2]
    assert isinstance(details_node, ContainerUnit)
    assert details_node.title == "Details"
    assert details_node.level == 3
    assert len(details_node.children) == 1
    assert isinstance(details_node.children[0], ParagraphBlock)

    # Child 2: ContainerUnit "Module 2: Adapters"
    mod2 = root.children[2]
    assert isinstance(mod2, ContainerUnit)
    assert mod2.title == "Module 2: Adapters"
    assert mod2.level == 2
    assert len(mod2.children) == 1
    assert isinstance(mod2.children[0], ParagraphBlock)


def test_text_source_adapter_parsing() -> None:
    """Verify plain text parsing into ParagraphBlocks in root container."""
    text_content = """First paragraph of plain text.
Second line of first paragraph.

Second paragraph of plain text.
"""

    stream = io.BytesIO(text_content.encode("utf-8"))
    adapter = TextSourceAdapter()
    doc = adapter.parse(stream, source_uri="notes.txt")

    assert doc.title == "notes"
    assert doc.source_type == "text"
    assert doc.provenance_info is not None
    assert doc.provenance_info.adapter_name == "TextSourceAdapter"

    assert len(doc.root_containers) == 1
    root = doc.root_containers[0]
    assert len(root.children) == 2
    assert isinstance(root.children[0], ParagraphBlock)
    assert isinstance(root.children[1], ParagraphBlock)


def test_source_adapter_parse_error() -> None:
    """Verify raising SourceAdapterParseError on corrupted or invalid streams."""
    # Invalid UTF-8 byte stream
    bad_bytes = b"\x80\x81\xff\xfe\xa0"
    stream = io.BytesIO(bad_bytes)
    adapter = MarkdownSourceAdapter()

    with pytest.raises(SourceAdapterParseError):
        adapter.parse(stream, source_uri="bad_file.md")

    # Faulty stream
    class FaultyStream(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            raise IOError("Stream read hardware error")

    faulty_stream = FaultyStream()
    with pytest.raises(SourceAdapterParseError):
        adapter.parse(faulty_stream, source_uri="faulty.md")
