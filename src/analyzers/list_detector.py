"""
ListDetectorAnalyzer — group consecutive ParagraphBlock items with leading
list markers into ListBlock/ListItemBlock (KRM_ENTITIES_MAP P0.1).

Recognized markers (case-insensitive):
    • ‣ ∙ ◦ ▪ ▫ ■ □ ● ○ * - – —      → list_style="bullet"
    1. 1)                            → list_style="ordered"
    a. a) а. а)                      → list_style="alpha"
    i. iv) IX)                       → list_style="roman"

A group requires ≥2 consecutive items so a single dashed paragraph is not
promoted. The marker is stripped from the first inline's text and preserved
on ListItemBlock.marker for round-trip.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.models import (
    BaseKRMNode,
    ContainerUnit,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    ParagraphBlock,
    StructuralUnit,
)


_BULLET_CHARS = "•·‣∙◦▪▫■□●○*\\-–—"
_MARKER_RE = re.compile(
    r"""^\s*
    (?:
        (?P<bullet>[""" + _BULLET_CHARS + r"""])
      | (?P<num>\d{1,3})[.)]
      | (?P<alpha>[a-zа-я])[.)]
      | (?P<roman>[ivxlcdm]+)[.)]
    )
    \s+
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)


def _first_span_text(block: ParagraphBlock) -> str:
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            txt = getattr(span, "text", "")
            if txt:
                return str(txt)
    return ""


def _classify_marker(text: str) -> Optional[Tuple[str, str, str]]:
    """Return (list_style, marker, remainder) or None if not a list item."""
    m = _MARKER_RE.match(text)
    if not m:
        return None
    if m.group("bullet") is not None:
        style = "bullet"
    elif m.group("num") is not None:
        style = "ordered"
    elif m.group("roman") is not None and _ROMAN_RE.match(m.group("roman") or ""):
        # A single "i" or "a" is ambiguous; prefer roman only when >1 char
        # so plain "a) foo" stays alpha.
        style = "roman" if len(m.group("roman")) > 1 else "alpha"
    elif m.group("alpha") is not None:
        style = "alpha"
    else:
        return None
    marker = text[m.start(): m.end()].strip()
    remainder = text[m.end():]
    return style, marker, remainder


def _strip_marker(block: ParagraphBlock, remainder: str) -> None:
    """Replace the first span's text with `remainder`, preserving spans."""
    for inline in block.inlines or []:
        for span in getattr(inline, "spans", []) or []:
            if getattr(span, "text", ""):
                span.text = remainder
                return


class ListDetectorAnalyzer(BaseAnalyzer):
    """
    Group consecutive marker-prefixed ParagraphBlocks into ListBlock nodes.

    Runs after HeadingAnalyzer (so the container tree exists) and before
    TitlePage/Table/Caption (so those analyzers see cleaner structure).
    """

    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="ListDetectorAnalyzer",
                version="1.0.0",
                description="Groups list-marker paragraphs into ListBlock/ListItemBlock",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.INSERT,
                    KRMPermission.MUTATE_ATTRIBUTES,
                },
                rg_permissions=set(),
                kg_permissions={KGPermission.READ},
                depends_on=["NormalizationAnalyzer", "HeadingAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        for root in doc.root_containers:
            self._process_container(root)

    def _process_container(self, container: ContainerUnit) -> None:
        # depth-first: transform children of nested containers first
        for child in container.children:
            if isinstance(child, ContainerUnit):
                self._process_container(child)

        new_children: List[BaseKRMNode] = []
        buffer: List[Tuple[ParagraphBlock, str, str]] = []  # (block, marker, style)

        def flush() -> None:
            if len(buffer) >= 2:
                items: List[ListItemBlock] = []
                styles = {s for _, _, s in buffer}
                # Mixed styles → pick the majority; keeps mixed lists as one block
                style = buffer[0][2] if len(styles) == 1 else max(
                    styles, key=lambda s: sum(1 for _, _, x in buffer if x == s)
                )
                for para, marker, _ in buffer:
                    items.append(
                        ListItemBlock(
                            marker=marker,
                            content=[para],
                            visual_layout=para.visual_layout,
                            extraction_confidence=para.extraction_confidence,
                            classification_confidence=0.85,
                            confidence_score=min(para.extraction_confidence, 0.85),
                        )
                    )
                new_children.append(
                    ListBlock(
                        list_style=style,
                        items=items,
                        classification_confidence=0.85,
                        confidence_score=0.85,
                    )
                )
            else:
                for para, _, _ in buffer:
                    new_children.append(para)
            buffer.clear()

        for child in container.children:
            if isinstance(child, ParagraphBlock) and not child.is_tombstoned:
                text = _first_span_text(child)
                classified = _classify_marker(text) if text else None
                if classified:
                    style, marker, remainder = classified
                    _strip_marker(child, remainder)
                    buffer.append((child, marker, style))
                    continue
            flush()
            new_children.append(child)

        flush()
        container.children = new_children
