"""reading_order: The analyzer itself: orchestration and KRM writes."""

from typing import Any, Dict, List, Optional
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission, RGPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph, ReadingTrack
from src.krm.models import (
    BaseKRMNode,
    CodeBlock,
    ContainerUnit,
    FigureBlock,
    FootnoteRefSpan,
    FormulaBlock,
    InlineUnit,
    KnowledgeDocument,
    ParagraphBlock,
    StructuralUnit,
    TableBlock,
)

from src.analyzers.reading_order.signals import _LEAF_TYPES

class ReadingOrderAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="ReadingOrderAnalyzer",
                version="1.0.0",
                description="Builds reading order edges from document structure",
                krm_permissions={KRMPermission.READ},
                rg_permissions={RGPermission.MUTATE_EDGES},
                kg_permissions=set(),
                depends_on=[],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        leaves: List[StructuralUnit] = []
        footnote_refs: List[tuple] = []  # (parent_block_id, footnote_id)

        def _collect(node: BaseKRMNode, parent_block_id: str = "") -> None:
            if isinstance(node, ContainerUnit):
                for child in node.children:
                    _collect(child, parent_block_id)
            elif isinstance(node, _LEAF_TYPES):
                leaves.append(node)  # type: ignore[arg-type]
                if isinstance(node, ParagraphBlock):
                    for inline in node.inlines:
                        for span in inline.spans:
                            if isinstance(span, FootnoteRefSpan) and span.footnote_id:
                                footnote_refs.append((node.id, span.footnote_id))

        for container in doc.root_containers:
            _collect(container)

        # MAIN_FLOW edges between consecutive leaf blocks
        for i in range(1, len(leaves)):
            rg.add_step(
                leaves[i - 1].id,
                leaves[i].id,
                track=ReadingTrack.MAIN_FLOW,
                confidence=1.0,
                analyzer_name=self.manifest.name,
            )

        # CAPTION_FLOW for figures with captions
        for leaf in leaves:
            if isinstance(leaf, FigureBlock) and leaf.caption_id:
                rg.add_step(
                    leaf.id,
                    leaf.caption_id,
                    track=ReadingTrack.CAPTION_FLOW,
                    confidence=1.0,
                    analyzer_name=self.manifest.name,
                )

        # FOOTNOTE_FLOW
        for block_id, footnote_id in footnote_refs:
            rg.add_step(
                block_id,
                footnote_id,
                track=ReadingTrack.FOOTNOTE_FLOW,
                confidence=0.9,
                analyzer_name=self.manifest.name,
            )
