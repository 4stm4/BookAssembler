"""Helpers shared by the source adapters (RFC 0008).

`ContainerStack` nests containers by the heading level a source declares — DOCX
(`Heading 1..6`, `w:outlineLvl`) and HTML (`<h1>`–`<h6>`) state it outright, so
building the tree from it is reading structure, not inferring it, unlike PDF
where heading detection is a heuristic owned by `HeadingAnalyzer` (§5.2).

`render_markdown` is the one Markdown reader: a .md file and a notebook's
markdown cell are the same syntax and must not drift apart.
"""

import re
from typing import List, Optional

from src.krm.models import (
    CodeBlock,
    ContainerUnit,
    InlineUnit,
    KnowledgeDocument,
    ParagraphBlock,
    ProvenanceInfo,
    StructuralUnit,
    StyledTextSpan,
    TextLineInline,
)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


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


def render_markdown(
    text: str,
    stack: ContainerStack,
    doc: KnowledgeDocument,
    provenance: ProvenanceInfo,
    set_title_from_h1: bool = True,
) -> None:
    """Read Markdown into the container tree: headings, fenced code, paragraphs.

    Shared by the Markdown adapter and the notebook adapter's markdown cells.
    `set_title_from_h1` promotes the first level-1 heading to the document title,
    which a notebook wants only for its first cell.
    """
    paragraph_lines: List[str] = []
    code_lines: List[str] = []
    code_language: Optional[str] = None
    in_code_block = False
    title_taken = not set_title_from_h1

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        lines = [line.strip() for line in paragraph_lines if line.strip()]
        paragraph_lines = []
        if not lines:
            return
        inlines: List[InlineUnit] = [
            TextLineInline(
                spans=[StyledTextSpan(text=line, provenance_info=provenance)],
                provenance_info=provenance,
            )
            for line in lines
        ]
        stack.add(ParagraphBlock(inlines=inlines, provenance_info=provenance))

    def flush_code() -> None:
        nonlocal code_lines, code_language
        stack.add(
            CodeBlock(
                code_text="\n".join(code_lines),
                programming_language=code_language,
                provenance_info=provenance,
            )
        )
        code_lines = []
        code_language = None

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code_block:
                flush_code()
                in_code_block = False
            else:
                flush_paragraph()
                in_code_block = True
                code_language = stripped[3:].strip() or None
                code_lines = []
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if level == 1 and not title_taken:
                doc.title = title
                title_taken = True
            stack.open(title, level)
            continue

        if stripped:
            paragraph_lines.append(line)
        else:
            flush_paragraph()

    if in_code_block:
        flush_code()
    else:
        flush_paragraph()
