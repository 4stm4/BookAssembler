"""diagram: The analyzer itself: orchestration and KRM writes."""

from src.analyzers.access import page_of
from typing import Any, Dict, List, Optional, Tuple
from src.analyzers.base import AnalyzerManifest, BaseAnalyzer, KRMPermission
from src.graph.knowledge_graph import KnowledgeGraph
from src.graph.reading_graph import ReadingGraph
from src.krm.identity import derive_composite_id
from src.krm.models import (
    ContainerUnit,
    DiagramBlock,
    KnowledgeDocument,
    ParagraphBlock,
    UnknownBlock,
    VisualLayout,
    NormalizedRect,
)

from src.analyzers.diagram.signals import LEFT_PAD, MAX_LABEL_WIDTH, MAX_LABEL_WORDS, MIN_LABELS, PAD, RIGHT_PAD, _RE_FIGURE_CAPTION, _RE_SUBLABEL, log
from src.analyzers.diagram.rules import _bbox_of, _runs_on, _text_of

class DiagramDetectorAnalyzer(BaseAnalyzer):
    def __init__(self) -> None:
        super().__init__(
            AnalyzerManifest(
                name="DiagramDetectorAnalyzer",
                version="1.0.0",
                description="Clusters short labels on scanned pages into DiagramBlocks",
                krm_permissions={
                    KRMPermission.READ,
                    KRMPermission.INSERT,
                    KRMPermission.TOMBSTONE,
                },
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
        # Collect leaf paragraph blocks with their parent container, by page.
        by_page: Dict[int, List[Tuple[ParagraphBlock, ContainerUnit]]] = {}

        def walk(container: ContainerUnit) -> None:
            for child in container.children:
                if getattr(child, "is_tombstoned", False):
                    continue
                if isinstance(child, ContainerUnit):
                    walk(child)
                elif isinstance(child, (ParagraphBlock, UnknownBlock)) and not isinstance(child, DiagramBlock):
                    pg = page_of(child)
                    if pg is not None and _bbox_of(child) is not None:
                        by_page.setdefault(pg, []).append((child, container))

        for c in doc.root_containers:
            walk(c)

        count = 0
        for pg, items in by_page.items():
            count += self._detect_on_page(pg, items)
        if count:
            log.info("DiagramDetectorAnalyzer: %d diagram(s) detected", count)

    def _detect_on_page(
        self, page: int, items: List[Tuple[ParagraphBlock, ContainerUnit]]
    ) -> int:
        if len(items) < MIN_LABELS:
            return 0

        caption_text = ""
        caption_box: Optional[Tuple[float, float, float, float]] = None
        labels: List[Tuple[ParagraphBlock, ContainerUnit, str, Tuple[float, float, float, float]]] = []
        # neither labels nor body text: labels OCR ran together, wires it
        # read as letters - the figure's where they stand among its labels
        drawn: List[Tuple[ParagraphBlock, ContainerUnit, str, Tuple[float, float, float, float]]] = []
        prose: List[Tuple[float, float, float, float]] = []
        for block, parent in items:
            txt = _text_of(block)
            if not txt:
                continue
            bb = _bbox_of(block)
            # A real caption is short ("Figure 2-11 Data-related addressing modes"),
            # not an in-text reference ("Figure 2-5 shows how a program's code …").
            if not caption_text and _RE_FIGURE_CAPTION.match(txt) and len(txt.split()) <= 10:
                caption_text, caption_box = txt, bb
            if not bb:
                continue
            width = bb[2] - bb[0]
            is_sublabel = bool(_RE_SUBLABEL.match(txt))
            # A schematic label is a short AND narrow text block (or an (a)-(g)
            # sub-caption). Other blocks are body text where they run on.
            is_label = (len(txt.split()) <= MAX_LABEL_WORDS and width <= MAX_LABEL_WIDTH) or is_sublabel
            if is_label:
                labels.append((block, parent, txt, bb))
            elif _runs_on(block, txt):
                prose.append(bb)
            elif txt != caption_text:
                drawn.append((block, parent, txt, bb))

        # A diagram region needs a real Figure caption and a cluster of narrow labels.
        if not caption_text or len(labels) < MIN_LABELS:
            return 0
        # Its labels stand by its caption: over it up to the body text over
        # it, or under it down to the body text under it - not every short
        # line of the page. Taken from the whole page, a book's worked
        # examples ("or \"377\" in octal.", "010 001 001") went into the
        # figure over them and out of the text.
        if caption_box is not None:
            labels = _by_caption(labels, prose, caption_box)
            if len(labels) < MIN_LABELS:
                return 0

        # Region = bbox of all clustered labels, padded (extra on the right for
        # arrows/boxes that extend beyond the text labels).
        x0 = min(b[3][0] for b in labels)
        y0 = min(b[3][1] for b in labels)
        x1 = max(b[3][2] for b in labels)
        y1 = max(b[3][3] for b in labels)
        # what else OCR read among the labels is the figure's too - not a
        # text column's running by it
        labels += [d for d in drawn if x0 <= (d[3][0] + d[3][2]) / 2 <= x1 and y0 <= (d[3][1] + d[3][3]) / 2 <= y1
                   and not _in_column(d[3], prose, y0, y1)]
        region = NormalizedRect(
            max(0.0, x0 - LEFT_PAD), max(0.0, y0 - PAD),
            min(1.0, x1 + RIGHT_PAD), min(1.0, y1 + PAD),
        )

        diagram = DiagramBlock(
            # Built from the labels it absorbs, so its identity is theirs
            # (RFC 0009 §5.2) — the uuid4 default made two runs disagree.
            id=derive_composite_id("diagram", *(b.id for b, _p, _t, _bb in labels)),
            caption_text=caption_text,
            labels=[{"text": t, "x0": bb[0], "y0": bb[1], "x1": bb[2], "y1": bb[3]}
                    for _b, _p, t, bb in labels],
            visual_layout=VisualLayout(bounding_box=region, page_or_screen_index=page),
            extraction_confidence=0.85,
            classification_confidence=0.80,
            confidence_score=0.80,
        )

        # Insert the diagram at the position of the first label, tombstone the rest.
        first_parent = labels[0][1]
        first_block = labels[0][0]
        try:
            idx = first_parent.children.index(first_block)
        except ValueError:
            idx = 0
        first_parent.children.insert(idx, diagram)

        for block, parent, _txt, _bb in labels:
            block.is_tombstoned = True
            if not block.metadata:
                block.metadata = {}
            block.metadata["tombstone_reason"] = f"absorbed_into_diagram:{diagram.id}"

        return 1


def _by_caption(labels: List[Any], prose: List[Tuple[float, float, float, float]],
                caption: Tuple[float, float, float, float]) -> List[Any]:
    """The labels a figure's caption has by it: those over the caption and
    under the body text nearest over it, or else those under the caption
    and over the body text nearest under it - the side with more.

    The body text that bounds the figure runs across from its caption. A
    column of text running down beside the figure - the Intel 3000
    manual's, by its block diagram - bounds nothing, and the short lines
    standing in it, its headings ("ACCUMULATOR AND D-BUS"), are its own."""
    across = [b for b in prose if b[0] < caption[2] and caption[0] < b[2]]
    top = max((b[3] for b in across if b[3] <= caption[1]), default=0.0)
    bottom = min((b[1] for b in across if b[1] >= caption[3]), default=1.0)
    over = [l for l in labels if l[3][1] >= top and l[3][3] <= caption[3]
            and not _in_column(l[3], prose, top, caption[1])]
    under = [l for l in labels if l[3][1] >= caption[1] and l[3][3] <= bottom
             and not _in_column(l[3], prose, caption[3], bottom)]
    return over if len(over) >= len(under) else under


def _in_column(box: Tuple[float, float, float, float], prose: List[Tuple[float, float, float, float]],
               top: float, bottom: float) -> bool:
    """Whether a box stands in a column of body text: text of its column
    over it and under it, both between top and bottom."""
    middle = (box[0] + box[2]) / 2
    height = box[3] - box[1]
    column = [b for b in prose if b[0] <= middle <= b[2] and b[3] > top and b[1] < bottom]
    return (any(b[3] <= box[1] + height for b in column)
            and any(b[1] >= box[3] - height for b in column))
