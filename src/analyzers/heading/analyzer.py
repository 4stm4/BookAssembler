"""heading: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import block_text, font_size
from typing import Any, Dict, List, Optional
from src.analyzers.base import (
    AnalyzerManifest,
    BaseAnalyzer,
    KGPermission,
    KRMPermission,
)
from src.graph.knowledge_graph import KGEntityNode, KnowledgeGraph, RelationType
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import ContainerUnit, KnowledgeDocument, NormalizedRect, ParagraphBlock, UnknownBlock, VisualLayout
from src.graph.knowledge_graph import EntityType

from src.analyzers.heading.rules import (
    _collect_containers, _detect_heading_threshold, _heading_level, _is_heading, _is_monospace,
    _is_printed_heading, _printed, _printed_under, body_size, heading_runs, printed_levels,
)

class HeadingAnalyzer(BaseAnalyzer):
    """
    Builds the heading hierarchy (RFC 0008 §5.2: this is analysis, not adapter work).
    Promotes large-font ParagraphBlocks to ContainerUnit headings and nests the
    intervening content, preserving node identity (RFC 0001 §2.3).
    """

    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="HeadingAnalyzer",
                version="2.0.0",
                description="Detects headings by typography and builds the container tree",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.TRANSFORM_NODE,
                    KRMPermission.INSERT,
                    # a block a heading was run into, split and tombstoned
                    KRMPermission.MUTATE_ATTRIBUTES,
                    KRMPermission.TOMBSTONE,
                },
                rg_permissions=set(),
                kg_permissions={KGPermission.READ, KGPermission.MUTATE_ENTITIES, KGPermission.MUTATE_EDGES},
                depends_on=["NormalizationAnalyzer"],
            )
        )

    def run(
        self,
        doc: KnowledgeDocument,
        rg: ReadingGraph,
        kg: KnowledgeGraph,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        # 1. Global body-font threshold across all ParagraphBlocks.
        sizes: List[float] = []
        for root in doc.root_containers:
            for blk in root.children:
                if (
                    isinstance(blk, (ParagraphBlock, UnknownBlock))
                    and not blk.is_tombstoned
                    and not _is_monospace(blk)
                ):
                    sizes.append(font_size(blk, default=12.0))
        threshold = _detect_heading_threshold(sizes)

        # 2. Promote headings and build the container tree per root.
        for root in doc.root_containers:
            self._build_tree(root, threshold)

        # 3. Validate hierarchy + emit KG entities and CONTINUATION_OF edges.
        containers: List[ContainerUnit] = []
        _collect_containers(doc.root_containers, containers)

        prev_level = 0
        prev_at_level: Dict[int, ContainerUnit] = {}
        for container in containers:
            if container.level > prev_level + 1 and prev_level > 0:
                container.confidence_score = 0.5
                container.metadata["heading_violation"] = True

            entity = KGEntityNode(
                id=container.id,
                name=container.title or f"Section L{container.level}",
                entity_type=EntityType.CONCEPT_TERM,
            )
            kg.add_entity(entity)

            if container.level in prev_at_level:
                kg.add_edge(
                    prev_at_level[container.level].id,
                    container.id,
                    RelationType.CONTINUATION_OF,
                    confidence=1.0,
                    analyzer_name=self.manifest.name,
                )
            prev_at_level[container.level] = container
            prev_level = container.level

    def _build_tree(self, root: ContainerUnit, threshold: float) -> None:
        """Re-nest root's flat children into a heading hierarchy.

        Only restructures when the adapter delivered a flat block list. If the
        tree already contains nested ContainerUnits (idempotency / non-PDF
        sources), it is left untouched.
        """
        flat = list(root.children)
        # The contents container TocAnalyzer builds on the flat list is a
        # leaf here, not a sign the tree was already structured.
        if any(isinstance(c, ContainerUnit) and c.semantic_type != "toc" for c in flat):
            return  # already structured

        root.children = []
        stack: List[ContainerUnit] = [root]
        body = body_size([b for b in flat if not b.is_tombstoned])
        # the headings OCR ran into body text, blocks of their own
        flat = _split_at_headings(flat, body)
        live = [b for b in flat if not b.is_tombstoned]
        position = {id(b): k for k, b in enumerate(live)}

        # A scanned page's block is judged by its print (PrintedLinesAnalyzer)
        # - OCR's sizes say nothing of it: a diagram's label it sized 10.8pt
        # on a 7.6pt page came out a heading - and ranked by its print.
        printed_headings = [b for b in live if _printed(b) and _is_printed_heading(
            b, _printed_under(live, position[id(b)] + 1), body)]
        printed_ids = {id(b) for b in printed_headings}
        levels = printed_levels(printed_headings, body)

        for block in flat:
            if block.is_tombstoned:
                # Already removed by an earlier analyzer (a repeating
                # running header, an absorbed table row, …). Promoting it
                # to a heading here would create a fresh, non-tombstoned
                # ContainerUnit at the same id — resurrecting the node and
                # tripping the No Silent Deletions guard (RFC 0001 §2.4).
                stack[-1].children.append(block)
            elif id(block) in printed_ids or (not _printed(block) and _is_heading(block, threshold)):
                text = block_text(block)
                level = levels.get(id(block)) or _heading_level(font_size(block, default=12.0), threshold)
                while len(stack) > 1 and stack[-1].level >= level:
                    stack.pop()

                heading = ContainerUnit(
                    title=text,
                    level=level,
                    visual_layout=block.visual_layout,
                    extraction_confidence=block.extraction_confidence,
                    classification_confidence=0.75,
                    confidence_score=min(block.extraction_confidence, 0.75),
                )
                heading.id = block.id  # RFC 0001 §2.3: identity preserved
                heading.provenance_info = block.provenance_info
                printed = (block.metadata or {}).get("printed_lines") or []
                if printed:
                    # set as printed, like a contents heading - a heading
                    # of two lines, both
                    heading.metadata["printed_title"] = {**printed[0], "part": "heading"}
                    if len(printed) > 1:
                        heading.metadata["printed_title_lines"] = [{**l, "part": "heading"} for l in printed]
                stack[-1].children.append(heading)
                stack.append(heading)
            else:
                stack[-1].children.append(block)


def _split_at_headings(flat: List[Any], body: float) -> List[Any]:
    """Each block a heading was run into (rules.heading_runs) as its pieces,
    each with its lines and their print; the block tombstoned (RFC 0001
    SS2.4), as a list OCR set in one block is split."""
    out: List[Any] = []
    for block in flat:
        pieces = (heading_runs(block, body) if isinstance(block, (ParagraphBlock, UnknownBlock))
                  and not block.is_tombstoned else [])
        if not pieces:
            out.append(block)
            continue
        printed = list((block.metadata or {}).get("printed_lines") or [])
        for k, lines in enumerate(pieces):
            texts = {" ".join(getattr(sp, "text", "") for sp in il.spans).strip() for il in lines}
            boxes = [il.visual_layout.bounding_box for il in lines
                     if getattr(il, "visual_layout", None) is not None and il.visual_layout.bounding_box]
            vl = block.visual_layout
            piece = type(block)(
                id=derive_composite_id("heading-split", block.id, str(k)),
                inlines=lines,
                parent_container_id=block.parent_container_id,
                provenance_info=block.provenance_info,
                visual_layout=VisualLayout(
                    bounding_box=NormalizedRect(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                                                max(b.x1 for b in boxes), max(b.y1 for b in boxes)),
                    page_or_screen_index=vl.page_or_screen_index, style=vl.style,
                ) if boxes and vl is not None else vl,
                extraction_confidence=block.extraction_confidence,
                classification_confidence=block.classification_confidence,
                confidence_score=block.confidence_score,
            )
            own = [pl for pl in printed if (pl.get("text") or "").strip() in texts]
            if own:
                piece.metadata["printed_lines"] = own
            out.append(piece)
        block.is_tombstoned = True
        block.metadata = {**(block.metadata or {}), "tombstone_reason": "split_at_heading"}
        out.append(block)
    return out
