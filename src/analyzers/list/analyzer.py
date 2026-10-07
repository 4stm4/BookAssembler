"""list: The analyzer itself: orchestration and KRM writes."""

from typing import Any, Dict, List, Optional, Tuple
from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import (
    BaseKRMNode,
    ContainerUnit,
    KnowledgeDocument,
    ListBlock,
    ListItemBlock,
    NormalizedRect,
    ParagraphBlock,
    StructuralUnit,
    UnknownBlock,
    VisualLayout,
)

from src.analyzers.list.rules import _classify_marker, _first_span_text, _items_in_block, _line_text, _strip_marker

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
                    KRMPermission.TOMBSTONE,
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

        container.children = self._split_lists(container.children)
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
                            id=derive_composite_id("list-item", para.id),
                            marker=marker,
                            content=[para],
                            visual_layout=para.visual_layout,
                            extraction_confidence=para.extraction_confidence,
                            classification_confidence=0.85,
                            confidence_score=min(para.extraction_confidence, 0.85),
                        )
                    )
                boxes = [p.visual_layout.bounding_box for p, _, _ in buffer
                         if p.visual_layout is not None and p.visual_layout.bounding_box is not None]
                pages = {p.visual_layout.page_or_screen_index for p, _, _ in buffer if p.visual_layout is not None}
                new_children.append(
                    ListBlock(
                        id=derive_composite_id(
                            "list", *[p.id for p, _, _ in buffer]
                        ),
                        list_style=style,
                        items=items,
                        classification_confidence=0.85,
                        confidence_score=0.85,
                        # where it printed, its items' boxes together: without
                        # one, a page set it after all else on the page
                        visual_layout=VisualLayout(
                            bounding_box=NormalizedRect(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                                                        max(b.x1 for b in boxes), max(b.y1 for b in boxes)),
                            page_or_screen_index=pages.pop(),
                        ) if boxes and len(pages) == 1 else None,
                    )
                )
            else:
                for para, _, _ in buffer:
                    new_children.append(para)
            buffer.clear()

        for child in container.children:
            if isinstance(child, (ParagraphBlock, UnknownBlock)) and not child.is_tombstoned:
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

    @staticmethod
    def _split_lists(children: List[BaseKRMNode]) -> List[BaseKRMNode]:
        """A list OCR set in one block (rules._items_in_block) split into a
        block per item, each with its lines and their print; the block
        tombstoned (RFC 0001 SS2.4)."""
        out: List[BaseKRMNode] = []
        for child in children:
            items = (_items_in_block(child) if isinstance(child, (ParagraphBlock, UnknownBlock))
                     and not child.is_tombstoned else None)
            if not items:
                out.append(child)
                continue
            printed = list((child.metadata or {}).get("printed_lines") or [])
            for k, lines in enumerate(items):
                texts = [_line_text(il) for il in lines]
                boxes = [il.visual_layout.bounding_box for il in lines
                         if getattr(il, "visual_layout", None) is not None and il.visual_layout.bounding_box]
                vl = child.visual_layout
                piece = type(child)(
                    id=derive_composite_id("list-item-text", child.id, str(k)),
                    inlines=lines,
                    parent_container_id=child.parent_container_id,
                    provenance_info=child.provenance_info,
                    visual_layout=VisualLayout(
                        bounding_box=NormalizedRect(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                                                    max(b.x1 for b in boxes), max(b.y1 for b in boxes)),
                        page_or_screen_index=vl.page_or_screen_index, style=vl.style,
                    ) if boxes and vl is not None else vl,
                    extraction_confidence=child.extraction_confidence,
                    classification_confidence=child.classification_confidence,
                    confidence_score=child.confidence_score,
                )
                own = [pl for pl in printed if pl.get("text") in texts]
                if own:
                    piece.metadata["printed_lines"] = own
                out.append(piece)
            child.is_tombstoned = True
            child.metadata = {**(child.metadata or {}), "tombstone_reason": "split_into_list_items"}
            out.append(child)
        return out
