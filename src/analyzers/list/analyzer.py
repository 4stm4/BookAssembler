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
    ParagraphBlock,
    StructuralUnit,
)

from src.analyzers.list.rules import _classify_marker, _first_span_text, _strip_marker

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
                            id=derive_composite_id("list-item", para.id),
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
                        id=derive_composite_id(
                            "list", *[p.id for p, _, _ in buffer]
                        ),
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
