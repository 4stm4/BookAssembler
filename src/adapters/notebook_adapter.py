"""
Jupyter Notebook Source Adapter for Knowledge Assembly Engine (KAE), RFC 0008 §3.4.

Markdown cells are read as Markdown, code cells become CodeBlocks tagged with the
kernel language, and cell outputs become blocks of their own — a figure for an
image, preformatted text for stdout and results, a traceback for an error.

Each output records the id of the cell that produced it in
`metadata["produced_by_cell_id"]`. The KG edge that states the relation
(CONCRETIZES, RFC 0008 §3.4) is written by NotebookOutputAnalyzer: an adapter has
no graph permissions and no business logic (RFC 0005 §2, RFC 0008 §5.2).

Guarantees:
- Strict typing (100% mypy --strict compatible)
- Standard library dependencies only (json, hashlib, base64)
- Exception wrapping: raises SourceAdapterParseError on malformed notebooks
"""

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, BinaryIO, Dict, List, Optional

from src.adapters._shared import ContainerStack, fallback_title, render_markdown
from src.adapters.base import (
    AdapterCapabilities,
    BaseSourceAdapter,
    SourceAdapterParseError,
)
from src.krm.models import (
    CodeBlock,
    FigureBlock,
    KnowledgeDocument,
    ProvenanceInfo,
    StructuralUnit,
)

# Preferred first: a picture of the result beats its repr.
_IMAGE_MIMES = ("image/png", "image/jpeg", "image/svg+xml", "image/gif")


def _source_text(cell: Dict[str, Any]) -> str:
    """Notebook `source` is either a string or a list of lines."""
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    return str(source)


def _output_text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return str(value)


def _kernel_language(notebook: Dict[str, Any]) -> Optional[str]:
    metadata = notebook.get("metadata") or {}
    language_info = metadata.get("language_info") or {}
    name = language_info.get("name")
    if not name:
        kernelspec = metadata.get("kernelspec") or {}
        name = kernelspec.get("language") or kernelspec.get("name")
    return str(name) if name else None


class NotebookSourceAdapter(BaseSourceAdapter):
    """Source Adapter for Jupyter notebooks (.ipynb)."""

    def __init__(self, capabilities: Optional[AdapterCapabilities] = None) -> None:
        if capabilities is None:
            capabilities = AdapterCapabilities(
                adapter_name="NotebookSourceAdapter",
                supported_extensions=["ipynb"],
                supported_mimeTypes=["application/x-ipynb+json"],
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
        """Parse an .ipynb binary stream into an Unprocessed KRM KnowledgeDocument."""
        if stream is None:
            raise SourceAdapterParseError("Input stream is None")

        try:
            raw_bytes = stream.read()
        except Exception as e:
            raise SourceAdapterParseError(f"Failed to read notebook stream: {e}") from e
        if not isinstance(raw_bytes, bytes):
            raise SourceAdapterParseError("Stream read did not return bytes")

        try:
            notebook = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise SourceAdapterParseError(f"Notebook is not valid JSON: {e}") from e
        if not isinstance(notebook, dict):
            raise SourceAdapterParseError("Notebook JSON root is not an object")

        cells = notebook.get("cells")
        if not isinstance(cells, list):
            raise SourceAdapterParseError("Notebook has no 'cells' array")

        provenance = ProvenanceInfo(
            adapter_name=self.capabilities.adapter_name,
            extraction_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )
        doc = KnowledgeDocument(
            title=fallback_title(source_uri),
            source_uri=source_uri,
            source_type="notebook",
            provenance_info=provenance,
            metadata={"cell_count": len(cells)},
        )

        language = _kernel_language(notebook)
        if language:
            doc.metadata["kernel_language"] = language

        stack = ContainerStack(doc, provenance)
        title_pending = True

        for cell in cells:
            if not isinstance(cell, dict):
                continue
            cell_type = cell.get("cell_type")
            text = _source_text(cell)

            if cell_type == "markdown":
                if text.strip():
                    render_markdown(
                        text, stack, doc, provenance, set_title_from_h1=title_pending
                    )
                    title_pending = False
                continue

            if cell_type != "code" or not text.strip():
                continue

            code = CodeBlock(
                code_text=text.rstrip("\n"),
                programming_language=language,
                provenance_info=provenance,
            )
            execution_count = cell.get("execution_count")
            if execution_count is not None:
                code.metadata["execution_count"] = execution_count
            stack.add(code)

            for output in cell.get("outputs") or []:
                if isinstance(output, dict):
                    stack.add(self._output_block(output, code.id, provenance))

        if not doc.root_containers:
            stack.current()
        return doc

    def _output_block(
        self, output: Dict[str, Any], cell_id: str, provenance: ProvenanceInfo
    ) -> Optional[StructuralUnit]:
        """One cell output as a KRM block, tagged with the cell that produced it."""
        block = self._build_output(output, provenance)
        if block is None:
            return None
        block.metadata["produced_by_cell_id"] = cell_id
        block.metadata["output_type"] = output.get("output_type", "")
        return block

    def _build_output(
        self, output: Dict[str, Any], provenance: ProvenanceInfo
    ) -> Optional[StructuralUnit]:
        output_type = output.get("output_type")

        if output_type == "stream":
            text = _output_text(output.get("text", "")).rstrip("\n")
            return (
                CodeBlock(code_text=text, provenance_info=provenance)
                if text.strip()
                else None
            )

        if output_type == "error":
            traceback = "\n".join(
                str(line) for line in output.get("traceback") or []
            ).rstrip("\n")
            summary = ": ".join(
                str(part)
                for part in (output.get("ename"), output.get("evalue"))
                if part
            )
            text = traceback or summary
            return (
                CodeBlock(code_text=text, provenance_info=provenance)
                if text.strip()
                else None
            )

        if output_type in ("display_data", "execute_result"):
            data = output.get("data") or {}
            for mime in _IMAGE_MIMES:
                if mime in data:
                    return FigureBlock(
                        image_uri=_data_uri(mime, _output_text(data[mime])),
                        mime_type=mime,
                        alt_text=_output_text(data.get("text/plain", "")).strip()
                        or None,
                        provenance_info=provenance,
                    )
            # text/plain accompanies richer types (a DataFrame ships both HTML
            # and its repr), so it is the honest fallback: rendering the HTML
            # would be interpretation, which belongs to an analyzer.
            text = _output_text(data.get("text/plain", "")).rstrip("\n")
            return (
                CodeBlock(code_text=text, provenance_info=provenance)
                if text.strip()
                else None
            )

        return None


def _data_uri(mime: str, payload: str) -> str:
    """Self-contained reference to an embedded output image."""
    if mime == "image/svg+xml":
        encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    compact = "".join(payload.split())
    try:
        base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return f"data:{mime};base64,"
    return f"data:{mime};base64,{compact}"
