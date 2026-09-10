"""Helpers shared by the source adapters (RFC 0008).

`ContainerStack` nests containers by the heading level a source declares — DOCX
(`Heading 1..6`, `w:outlineLvl`) and HTML (`<h1>`–`<h6>`) state it outright, so
building the tree from it is reading structure, not inferring it, unlike PDF
where heading detection is a heuristic owned by `HeadingAnalyzer` (§5.2).
"""

from typing import List, Optional


def fallback_title(source_uri: str) -> str:
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

from src.krm.models import (
    ContainerUnit,
    KnowledgeDocument,
    ProvenanceInfo,
    StructuralUnit,
)


class ContainerStack:
    """Builds the ContainerUnit hierarchy of a document from heading levels."""

    def __init__(self, doc: KnowledgeDocument, provenance: ProvenanceInfo) -> None:
        self._doc = doc
        self._provenance = provenance
        self._stack: List[ContainerUnit] = []

    def open(self, title: str, level: int) -> ContainerUnit:
        """Start a container at `level`, nested under the nearest shallower one."""
        container = ContainerUnit(
            title=title, level=level, provenance_info=self._provenance
        )

        while self._stack and self._stack[-1].level >= level:
            self._stack.pop()

        if self._stack:
            container.parent_container_id = self._stack[-1].id
            self._stack[-1].children.append(container)
        else:
            self._doc.root_containers.append(container)

        self._stack.append(container)
        return container

    def current(self) -> ContainerUnit:
        """Container that content belongs to, opening a root one if none exists."""
        if not self._stack:
            root = ContainerUnit(
                title=self._doc.title or "Main Content",
                level=1,
                provenance_info=self._provenance,
            )
            self._doc.root_containers.append(root)
            self._stack.append(root)
        return self._stack[-1]

    def add(self, block: Optional[StructuralUnit]) -> None:
        """Append a block to the current container."""
        if block is None:
            return
        container = self.current()
        block.parent_container_id = container.id
        container.children.append(block)
